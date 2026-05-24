# 防禦方法論

> **核心策略**：以乾淨語料庫為基準，透過 LLM 偵測事實矛盾與離題注入，阻擋惡意 chunks。  
> **防禦點 A**：入庫前矛盾偵測（Phase 2）  
> **防禦點 B**：檢索後雙重檢查——矛盾偵測 + 離題偵測（Phase 3）  
> **研究目標**：提升 DBR（Detection/Block Rate），降低 CDR（Clean Drop Rate）

---

## 防禦點概覽

| 防禦點 | 階段 | 方法 | 觸發條件 | 處置 |
|--------|------|------|---------|------|
| **A** | Phase 2 入庫前 | 矛盾偵測 | 新 chunk 與乾淨語料存在事實矛盾 | 阻擋入庫 |
| **B** | Phase 3 檢索後 | 矛盾偵測 + 離題偵測 | 矛盾 **或** 明顯來自不同法律領域 | 物理 DELETE + 移出 context |

---

## 防禦點 A：矛盾偵測（入庫前）

### 核心概念

資料庫中已有大量乾淨 CUAD chunks（`is_original=TRUE`）作為事實參考基準。  
攻擊者嘗試注入的 chunk 應與語意最相近的乾淨 chunks 在事實上一致。  
若出現矛盾（數字、日期、管轄地、金額），代表該 chunk 為惡意注入 → 阻擋入庫。

### 流程

```
新 chunk（Phase 2 注入前）
    ↓
1. Embed → pgvector 找 top_k_ref 筆語意最相近的乾淨 chunks（is_original=TRUE）
    ↓
2. LLM 矛盾偵測：新 chunk 是否與參考 chunks 存在事實矛盾？
   （數字 / 日期 / 金額 / 管轄地 / 截止期限 / 當事人名稱）
    ↓
   YES → is_malicious=True, score=1.0 → 阻擋入庫
   NO  → is_malicious=False, score=0.0 → 寫入 pgvector
   無參考 → is_malicious=False, score=0.5（資料不足，保守放行）
```

**偵測目標**：Hijack（✅）、Stealth（✅ 部分）  
**結構性弱點**：Blocker 不引入事實矛盾，Defense A 無法偵測。

---

## 防禦點 B：雙重檢查（檢索後）

### 核心概念

Phase 3 檢索後已有 **query context**，可在矛盾偵測基礎上加入**離題偵測**，針對 Blocker 攻擊。

Blocker 的特性：語意與 query 高度相似（能進入 top-k），但實際來自不同法律領域（例：用保密條款回應終止通知問題）。矛盾偵測對它無效，但「是否明顯來自不同法律領域」的判斷可以識別。

> **設計說明**：前一版 Stage 2 採用「可回答性」（"Can this chunk answer the query?"），實驗發現 CDR=91.3%（大量乾淨 chunks 被誤殺），因為同主題但不含精確答案的合法條款也會被擋。改用「離題偵測」（"Is this chunk from a completely different legal domain?"）更寬鬆、更精準，僅阻擋跨法律領域的注入。

### 流程（雙階段）

```
被檢索的 chunk（已在 top-k 中）＋ query text
    ↓
Stage 1：LLM 矛盾偵測（同 Defense A）
    ↓
   YES → score=1.0 → 物理 DELETE（Hijack / Stealth）
   NO  → 進入 Stage 2
    ↓
Stage 2：LLM 離題偵測
   「此 chunk 明顯來自與 query 完全不同的法律領域嗎？YES / NO」
    ↓
   YES → score=0.7 → 物理 DELETE（Blocker）
   NO  → score=0.0 → 保留進 sanitized context
```

### 分數語義

| score | 意義 | 阻擋 |
|-------|------|------|
| 1.0 | 事實矛盾（Hijack / Stealth） | ✅ |
| 0.7 | 明顯來自不同法律領域（Blocker） | ✅ |
| 0.5 | 無乾淨參考，資料不足 | ❌ 保守放行 |
| 0.0 | 通過所有檢查 | ❌ |

### 各攻擊類型偵測邏輯

```
Hijack / Stealth：
  惡意 chunk 修改關鍵數值（例：30天 → 15天）
  → Stage 1 偵測事實矛盾 → score=1.0 → BLOCK

Blocker：
  惡意 chunk 來自不同法律領域（例：保密條款注入至終止通知查詢）
  → Stage 1：無矛盾（pass）
  → Stage 2：「明顯來自不同法律領域？」→ YES → score=0.7 → BLOCK
```

### 設定參數（configs/experiment_01.yaml）

| 參數 | 值 | 說明 |
|------|----|------|
| `defense.llm_model` | `gemma4:e4b` | 用於兩階段 LLM 檢查的模型 |
| `defense.top_k_ref` | 5 | 矛盾偵測時的乾淨參考 chunks 數量 |

### 實作位置

```
src/defense/filter.py
    └── class ConsistencyDefenseFilter
            ├── predict(chunk_text, query_text=None) → (bool, float)
            │       Defense A: query_text=None（僅矛盾偵測）
            │       Defense B: query_text 傳入（矛盾偵測 + 離題偵測）
            ├── _check_contradiction(chunk, refs)    → bool  (Stage 1)
            ├── _check_off_topic(chunk, query)       → bool  (Stage 2, Defense B)
            ├── _retrieve_similar_clean(embedding)   → list  (pgvector 語意搜尋)
            └── from_config(config, conn)            → ConsistencyDefenseFilter
```

---

## 兩防禦點整合架構

```
[Phase 2 入庫前]   → 防禦點 A（矛盾偵測）
                       → 矛盾 → 阻擋入庫
                       → 通過 → 寫入 pgvector
        ↓
[pgvector DB]      ← 只有通過 A 的 chunks 進入
        ↓
[Phase 3 檢索後]   → 防禦點 B（矛盾偵測 + 離題偵測）
                       → 矛盾 (score=1.0) → 物理 DELETE
                       → 離題 (score=0.7) → 物理 DELETE
                       → 通過 → 進入 sanitized context
        ↓
[Phase 4 生成]     ← 只有通過 A + B 的乾淨 chunks
        ↓
[使用者輸出]        ← 基於乾淨語料的正確答案
```

### 各攻擊類型的預期防禦效果

| 攻擊類型 | 防禦點 A | 防禦點 B | 整體 |
|---------|---------|---------|------|
| Hijack  | ✅ 有效（明顯事實替換） | ✅ Stage 1 有效 | 強 |
| Stealth | ⚠️ 部分有效（細微矛盾，LLM 可能漏判） | ⚠️ Stage 1 部分有效 | 中 |
| Blocker | ❌ 無法偵測 | ⚠️ Stage 2 有效（跨領域注入），同領域 Blocker 仍有盲區 | 中 |

> **實驗結果（experiment_01，5 queries × 3 types，gemma4:e4b）**：Defense A DBR=40% / CDR-A=5%（blocker=0%, hijack=60%, stealth=60%）；Defense B（離題偵測）DBR=66.67% / CDR-B=43.48%。目前擴充至 10 queries × 3 types（30 poison chunks）與 200 筆乾淨語料，重跑實驗中。

---

## Phase 4 生成策略：RobustRAG Keyword Voting

> **注意**：這不是第三道防線，而是 Phase 4 的**答案生成策略**，與 Defense A / B 的 chunk 過濾機制完全獨立。

Phase 4 支援兩種生成模式（由 `config.generation.defense_mode` 控制）：

| 模式 | 說明 |
|------|------|
| `standard` | 所有 sanitized chunks 串接後一次生成答案 |
| `voting` | RobustRAG Keyword-based Aggregation（Xiang et al., 2024） |

### Voting 模式流程

```
top-k chunks（Defense B 後）
    ↓
均勻切成 g 組（round-robin，分散毒 chunk 風險）
    ↓
每組各自獨立跑一次 Target LLM → g 個 isolated responses
    ↓
從各 response 抽取關鍵字，投票保留 ≥ ceil(α × g) 組同意的詞
    ↓
將 g 個 responses 再餵給 LLM：
  「只回報大多數來源一致的資訊；若衝突請說明」
    ↓
最終答案
```

**防護原理**：毒 chunk 只在 1 組中，另外 g-1 組為乾淨資料；若毒組與乾淨組給出不同關鍵字（不同數字、不同地點），投票門檻使毒值無法通過。最終 LLM 被告知有衝突時會回報「資訊衝突」而非盲目接受毒值。

**設定參數**：`voting_groups: 3`、`voting_alpha: 0.5`（需 2/3 組同意）

---

## Ablation 配置

| 設定 | 說明 |
|------|------|
| `no_defense` | A、B 均關閉，純攻擊上限（基準線） |
| `only_A` | 僅入庫前矛盾偵測 |
| `only_B` | 僅檢索後雙重檢查 |
| `A + B` | 完整兩點防護（本研究主要設定） |

---

## 參考文獻

1. **RobustRAG** — Xiang et al., *"Certifiably Robust RAG against Retrieval Corruption"*, arXiv: 2405.15556 (2024)
   - Isolate-then-Aggregate 策略；keyword-based 與 decoding-based aggregation；可認證 robustness 保證

2. **PoisonedRAG** — Wei Zou et al., *"PoisonedRAG: Knowledge Corruption Attacks to RAG of Large Language Models"*, USENIX Security 2025. arXiv: 2402.07867
   - 攻擊框架來源；三種攻擊類型定義（Hijack / Blocker / Stealth）

3. **ContextCite** — *"ContextCite: Attributing Model Generation to Context"*, NeurIPS 2024
   - Post-hoc attribution：追溯 LLM 輸出至 source chunk；計算代價為原始 inference 的 32 倍，暫未實作
