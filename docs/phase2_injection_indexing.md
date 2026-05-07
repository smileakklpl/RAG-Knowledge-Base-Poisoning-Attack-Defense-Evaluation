# Phase 2：入庫與防禦點 A（Injection + Pre-Storage Defense）

## 目標

將 Phase 1 生成的中毒文本與 CUAD 正常語料一併送入 pgvector 向量資料庫；在寫入前**先經過防禦點 A**，被判定為惡意者**物理 DELETE 不寫入**，模擬「真實系統具備入庫前掃描」的防護情境。

---

## 輸入 / 輸出

| 項目 | 內容 |
|------|------|
| **輸入** | Phase 1 輸出的 Poisoned Chunks + CUAD 正常 Chunks |
| **輸出** | 已過濾的 pgvector 資料表（含 metadata） + 入庫防禦日誌 |
| **執行約束** | 不需要 LLM，只需 Embedding Model + 向量庫；防禦器 CPU 推論即可 |

---

## Clean Corpus 來源

| 資料集 | 角色 | 說明 |
|--------|------|------|
| **CUAD** | 主要語料 | 510 份英文商業法律合約，與攻擊領域一致 |

---

## 切段規則（Chunking）

固定化規則，避免不同實驗組之間因分塊差異不可比較：

| 參數 | 建議值 |
|------|--------|
| Chunk 大小 | 300～500 tokens |
| Overlap | 50～100 tokens |
| 分段依據 | 優先按段落，其次按 token 數截斷 |

Poisoned Chunk 長度應與 Clean Chunk 一致，避免長度特徵洩漏身份。

---

## Embedding Model

由 `configs/*.yaml` 的 `embedding_model` 欄位指定，本專題採用 `bge-m3`（多語言、向量維度 1024）。

---

## 向量資料庫：pgvector

### 為什麼選 pgvector

- **SQL 介面熟悉**：可直接以 Postgres 的 `DELETE` / `UPDATE` 操作清除中毒文本，符合「物理刪除」需求
- **支援 metadata 過濾**：`is_poison`、`is_blocked` 欄位可在 SQL `WHERE` 中直接過濾
- **HNSW / IVFFlat 索引**：原生支援高效近似最近鄰搜尋
- **持久化與備份**：使用 Postgres 標準工具，不需額外管理向量庫狀態

### Schema 定義

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id              SERIAL PRIMARY KEY,
    chunk_id        TEXT UNIQUE NOT NULL,
    document        TEXT NOT NULL,
    embedding       VECTOR(1024) NOT NULL,         -- bge-m3 維度
    doc_id          TEXT NOT NULL,
    source          TEXT NOT NULL,                  -- 'cuad' / 'phase1_poison'
    is_poison       BOOLEAN NOT NULL DEFAULT FALSE, -- ground truth 標籤（評估用）
    attack_type     TEXT,                           -- hijack / blocker / stealth / NULL
    chunk_index     INT,
    inserted_at     TIMESTAMP DEFAULT now()
);

-- HNSW 索引（推薦，平衡速度與召回率）
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
```

> `is_poison` 欄位在真實場景下攻擊者不會標記，這裡僅供實驗評估比對。

---

## 防禦點 A：入庫前過濾

### 流程

```
Phase 1 Poisoned Chunks + CUAD Clean Chunks
    │
    ▼
┌──────────────────────────────────────────┐
│  Defense Filter A                        │
│  (方法論見 docs/defense_methodology.md)  │
│                                          │
│  輸入：chunk_text                        │
│  輸出：is_malicious (bool) + score      │
└────────────┬─────────────────────────────┘
             │
       ┌─────┴─────┐
       │           │
   is_malicious   is_clean
       │           │
       ▼           ▼
  ❌ DELETE    ✅ INSERT INTO chunks
  （拒絕注入）  （寫入 pgvector）
       │           │
       ▼           ▼
  記錄到防禦日誌  建立 HNSW 索引
```

### 處置策略：標記 + 物理 DELETE + 重寫

判定為惡意的 chunk **完全不進入資料庫**，乾淨的 chunk 寫入後完成資料庫的最終狀態：

```python
audit_log_a = []

for chunk in candidate_chunks:
    score, is_malicious = defense_filter_a.predict(chunk.text)

    # 每筆都記錄，含 ground truth（來自 Phase 1 輸出 JSON）
    audit_log_a.append({
        "chunk_id":               chunk.chunk_id,
        "stage":                  "pre_injection",
        "defense_score":          score,
        "predicted_is_malicious": is_malicious,
        "ground_truth_is_poison": chunk.is_poison,   # 來自 Phase 1 metadata
        "source":                 chunk.source,
        "processed_at":           now_iso(),
    })

    if is_malicious:
        continue                  # 標記後跳過，不寫入資料庫
    db.insert(chunk)              # 乾淨者寫入 pgvector

save_jsonl("output/audit_defense_a.jsonl", audit_log_a)
```

**重要**：`audit_log_a` 必須記錄**所有**候選 chunk（不只被攔截的），否則計算 CDR-A 時分母（clean 總數）無從取得。

### 防禦日誌欄位說明

```json
{
  "chunk_id":               "poison_a3f2c1d8",
  "stage":                  "pre_injection",
  "defense_score":          0.87,
  "predicted_is_malicious": true,
  "ground_truth_is_poison": true,
  "source":                 "phase1_poison",
  "processed_at":           "2026-05-07T10:23:11"
}
```

| 欄位 | 用途 |
|------|------|
| `predicted_is_malicious` | 防禦器的判定，決定該 chunk 是否被刪除 |
| `ground_truth_is_poison` | Phase 1 的真實標籤，用於計算 **刪除成功率（DBR-A）** 與 **誤刪率（CDR-A）** |

兩者對齊，才能在事後從 JSONL 中推導完整混淆矩陣（TP / FP / TN / FN）。

---

## Poison Ratio（污染比例）

實驗必須跑以下三組：

| Poison Ratio | 說明 |
|-------------|------|
| 1% | 低強度，接近現實場景 |
| 5% | 中強度 |
| 10% | 高強度，測試防禦器極限 |

計算方式：`poison_count = int(total_chunks * poison_ratio)`

> 「Poison Ratio」是指**送入防禦點 A 的候選 chunks 中** 中毒文本佔比，而非最終資料庫中的比例。最終比例會因 DBR-A 而下降。

---

## Phase 2 指標

| 指標 | 公式 | 意義 |
|------|------|------|
| **DBR-A**（刪除成功率） | `predicted=True & truth=True` / `truth=True` | 惡意 chunk 被正確刪除的比例（Recall） |
| **CDR-A**（誤刪率） | `predicted=True & truth=False` / `truth=False` | 乾淨 chunk 被錯誤刪除的比例（False Positive Rate） |
| **Final Poison Ratio** | 寫入資料庫的 poison / 寫入資料庫的總數 | A 過濾後的殘留污染水準 |

兩個指標均從 `output/audit_defense_a.jsonl` 計算，無需查詢資料庫：

```python
import json

records = [json.loads(l) for l in open("output/audit_defense_a.jsonl")]

poison = [r for r in records if r["ground_truth_is_poison"]]
clean  = [r for r in records if not r["ground_truth_is_poison"]]

DBR_A = sum(r["predicted_is_malicious"] for r in poison) / len(poison)
CDR_A = sum(r["predicted_is_malicious"] for r in clean)  / len(clean)
```

---

## 實作注意事項

1. Chunk 規則在整個實驗中固定，不可在不同實驗組之間改動
2. 必須儲存 `embedding`、`document`、`doc_id`、`is_poison`、`source`，缺一無法做後續分析
3. 防禦點 A 的方法論（特徵、模型、閾值）統一寫在 `docs/defense_methodology.md`，本檔案不重複
4. 每次建庫都要記錄：使用的 config、seed、git commit hash
5. 常見踩雷：只看寫入後的 `is_poison` 比例，沒記錄被 DELETE 的 chunk → DBR-A 無法計算

---

## 與下一階段的銜接

Phase 2 結束後，pgvector 中的 chunks 表是「**過 A 防禦後的世界**」。Phase 3 會基於這份資料表執行檢索，並再經過 **防禦點 B** 過濾 Top-K 結果。
