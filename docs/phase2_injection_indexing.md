# Phase 2：注入與索引模組（Data Injection & Indexing）

## 目標

將 Phase 1 生成的中毒文本與正常語料庫混合，建立「受污染的向量資料庫」，模擬真實場景下攻擊者悄悄混入知識庫的情境。

---

## 輸入 / 輸出

| 項目 | 內容 |
|------|------|
| **輸入** | 中毒文本區塊（Poisoned Chunks）、大量正常文本區塊（Clean Chunks） |
| **輸出** | 受污染的向量資料庫（Poisoned Vector DB） |
| **執行約束** | 此階段不需要 LLM，只需 Embedding Model + 向量庫，可完全離線執行 |

---

## Clean Corpus 來源

| 資料集 | 角色 | 說明 |
|--------|------|------|
| **CUAD** | 主要語料 | 510 份英文商業法律合約，與攻擊領域一致，是 RAG 知識庫的主體 |

---

## RAG 知識庫的本質

RAG 的知識庫不需要 Q&A 格式，就是**切碎的純文字段落**。

```
原始文件（例如維基百科台灣條目）
    ↓ 切段（Chunking）
Chunk #001: "台灣，正式名稱為中華民國，位於東亞..."
Chunk #002: "台灣的首都為台北市，是全國政治、經濟..."
Chunk #003: "台灣的主要產業包括半導體製造、電子業..."
    ↓ Embedding 向量化
向量: [0.12, -0.87, 0.34, ...]  （每個 Chunk 對應一個高維向量）
    ↓ 存入向量資料庫
Vector DB（含向量 + 原始文字 + metadata）
```

攻擊者就是把惡意 Chunk 偽裝成正常 Chunk，混進這個資料夾。

---

## 切段規則（Chunking）

規則必須固定化，避免因分塊差異造成結果不可比較：

| 參數 | 建議值 |
|------|--------|
| Chunk 大小 | 300～500 tokens |
| Overlap | 50～100 tokens（避免句子在邊界斷裂） |
| 分段依據 | 優先按段落，其次按 token 數截斷 |

Poisoned Chunk 長度應與 Clean Chunk 一致，避免長度特徵洩漏身份。

---

## Embedding Model

模型由 `configs/*.yaml` 的 `embedding_model` 欄位指定。

| 模型 | 大小 | 適用場景 |
|------|------|---------|
| `BAAI/bge-m3` | ~570MB | 多語言，本專題優先選項 |
| `BAAI/bge-base-zh` | ~400MB | 中文效果好，體積小 |
| `intfloat/e5-base` | ~438MB | 英文語料 |

所有模型均可在 5070 Ti + 32GB RAM 環境本地穩定運行。

---

## 向量資料庫選型

| 向量庫 | 特性 | 建議使用場景 |
|--------|------|-------------|
| **ChromaDB** | 最易上手，本地持久化，Python 原生 | 開發初期、MVP 驗證 |
| **FAISS** | Meta 出品，速度快，需自行管理持久化 | 中大型實驗，需控制索引類型 |
| **Qdrant** | 支援 metadata 過濾，REST API 完整 | 需要複雜查詢條件時 |

建議：**先用 ChromaDB 驗證流程，確認 RSR 後再考慮換 FAISS**。

---

## 向量庫儲存規範

每筆 Chunk 必須同時儲存以下欄位，只存向量不存原文會導致後續無法做防禦分析：

```python
{
    "id":        "chunk_001",
    "embedding": [0.12, -0.87, 0.34, ...],   # 向量
    "document":  "台灣的首都為台北市...",      # 原始文字
    "metadata": {
        "doc_id":    "wiki_taiwan_001",
        "source":    "wikipedia",
        "is_poison": False,                    # 關鍵標籤，用於後續評估
        "attack_type": None,                   # hijack / blocker / stealth / None
        "chunk_index": 2
    }
}
```

`is_poison` 欄位在**真實攻擊情境下攻擊者不會標記**，這裡標記是為了實驗評估使用。

---

## Poison Ratio（污染比例）

實驗必須跑以下三組，才有足夠說服力：

| Poison Ratio | 說明 |
|-------------|------|
| 1% | 低強度，接近現實場景 |
| 5% | 中強度 |
| 10% | 高強度，測試防禦器極限 |

計算方式：`poison_count = int(total_chunks * poison_ratio)`

---

## FAISS 索引類型注意事項

若使用 FAISS，索引類型會顯著影響 RSR，必須在 config 中固定並報告：

| 索引類型 | 特性 |
|---------|------|
| `IndexFlatL2` | 暴力搜尋，最精確，資料量小時優先 |
| `IndexIVFFlat` | 需先 train，速度快但有近似誤差 |
| `IndexHNSWFlat` | 圖結構索引，平衡速度與精確度 |

建議初期使用 `IndexFlatL2`，確保 RSR 計算不受近似誤差影響。

---

## 實作注意事項

1. Chunk 規則在整個實驗中必須固定，不可在不同實驗組之間改動
2. 向量庫需同時保存 `embedding`、`raw_text`、`doc_id`、`is_poison`、`source`
3. 每次建庫都要記錄：使用的 config、seed、git commit hash
4. 常見踩雷：只存向量不存原文與標籤，後續無法做防禦分析與錯誤追蹤
