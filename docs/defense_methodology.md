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

> **實驗結果（experiment_01，10 queries × 3 types = 30 poison，200 clean，40 CDR，gemma4:e4b）**：  
> Defense A — DBR-A=**46.67%** / CDR-A=**5.00%**（blocker=20%、hijack=50%、stealth=70%）；14 blocked，16 inserted。  
> Defense B — RSR=**90%**（防禦前，9/10 queries），DBR-B=**56.25%** / CDR-B=**40.00%**（blocker=38%、hijack=80%、stealth=67%）。  
> CDR-B 偏高主因為 Stage 2 離題偵測對同領域一般法律條款的誤判；Hijack 由 Stage 1 矛盾偵測有效清除（80%）。  
> **Phase 5 ASR（Voting）= 30%**（3/10 queries：q04 payment/full、q05 confidentiality/full、q06 auto-renewal/partial）。

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

**與原始 RobustRAG 的差異**：原論文的最終生成步驟以 voted keywords 作為輸出約束（只允許使用通過投票的關鍵字）；本實作改為將 g 個 isolated responses 全部送給 LLM，以共識萃取 prompt（「只回報大多數來源一致的資訊」）整合結果。voted keywords 仍有計算並記錄於輸出 log，但未直接約束生成。功能上類似，但非原版完整實作。

**設定參數**：`voting_groups: 3`、`voting_alpha: 0.5`（需 2/3 組同意）

---

---

## PPL 困惑度防禦（Ablation）

> **方法來源**：RAGuard: Secure RAG against Poisoning Attacks (2025) 提出的 Chunk-wise Perplexity Filtering，本研究以 GPT-2 small 實作 global PPL 與 sliding-window spike PPL 作為 Ablation 對照組。  
> **假設**：惡意注入文本（LLM 生成）的語言風格與自然文本有差異，PPL 應偏高。  
> **實作**：`src/defense/filter_PPL.py` — `PPLDefenseFilter`，API 與 `ConsistencyDefenseFilter` 相容。

### 參數設定（`configs/experiment_ppl_defense.yaml`）

| 防禦點 | global PPL 門檻 | spike PPL 門檻 |
|--------|----------------|---------------|
| **A（入庫前）** | 80.0 | 120.0 |
| **B（檢索後）** | 100.0 | 150.0 |

`window_size=50`，`stride=25`，`max_tokens=512`

### 流程

```
chunk text
    ↓
GPT-2 small 計算 global PPL
    ↓
  global PPL > threshold → is_malicious=True, score=1.0 → 阻擋
  否則 → sliding window spike PPL
    ↓
  spike PPL > spike_threshold → is_malicious=True, score=1.0 → 阻擋
  否則 → is_malicious=False, score=0.0 → 放行
```

### 實驗結果（experiment_ppl_defense，與 Voting 相同語料，gemma4:26b）

> Defense A — DBR-A=**20.00%** / CDR-A=**2.50%**（blocker=20%、hijack=20%、stealth=20%；均勻各擋 2/10）  
> Defense B — RSR=**100%**（10/10 queries）/ DBR-B=**0.00%** / CDR-B=**12.00%**  
> **Phase 5 ASR（PPL）= 60%**（6/10 queries：q01、q02、q04、q05、q06、q08）

### 失效根本原因

| 現象 | 原因 |
|------|------|
| DBR-A 低（20%）且均勻 | Stealth/Hijack 攻擊文本由 LLM 生成，句式流暢，PPL 與乾淨 chunks 無明顯差距 |
| DBR-B = 0% | 法律合約原文本身 PPL 天生偏高（法律術語密集、句式固定）；LLM 生成的毒文本語言更流暢，反而 PPL 更低 → **異常信號方向倒置** |
| CDR-B = 12% | 少數真實合約段落句式罕見，global PPL 超過門檻被誤攔 |

> **結論**：PPL 防禦的假設在法律合約 RAG 場景下不成立——對抗性文本不一定「不流暢」。在 LLM-generated 毒文本的場景下，語義一致性偵測（Voting）顯著優於統計型困惑度過濾。

---

## 五實驗最終比較

| 指標 | No Defense | Only A（消融） | Only B（消融） | PPL（A+B） | Voting（A+B） |
|------|-----------|--------------|--------------|-----------|-------------|
| DBR-A | 0% | **53.33%** | 0% | 20.00% | **46.67%** |
| CDR-A | 0% | **0.00%** | 0% | **2.50%** | 5.00% |
| RSR（pre-B） | 100% | 100% | 100% | 100% | **90%** |
| DBR-B | 0% | —（B 關閉） | **76.67%** | 0% | **56.25%** |
| CDR-B | 0% | —（B 關閉） | **37.50%** | **12.00%** | 40.00% |
| **ASR（Phase 5）** | 90% | **20%** | **70%** | 60% | **30%** |
| **ASR 降幅 vs 基準** | — | **▼70pp** | ▼20pp | ▼30pp | **▼60pp** |

> **消融結論**：Defense A 是主導防禦層——入庫前阻斷（Only A 實測 DBR-A=53.33%）使 Only A 單獨達到 ASR=20%（▼70pp），優於完整 Voting A+B（30%）。Only B（僅後過濾，DBR-B=76.67% / CDR-B=37.50%）ASR=70%（▼20pp），遜於 PPL A+B（60%），遠遜 Voting A+B——即使 DBR-B 高達 76.67%，在無 Defense A 把關入庫、全毒負載全數進 DB 的情況下，後過濾仍難以有效壓制攻擊。Defense B CDR-B=37.50% 誤殺乾淨 chunks 削弱 Phase 4 voting 信號，導致完整 A+B 效果反不如 Only A。降低 Defense B 的 CDR（提升 Stage 2 精確度）是改善管線的優先方向。

---

## 關鍵發現：Defense B 的乾淨誤殺副作用

**現象**：Only A（僅防禦點 A，ASR=20%）的最終防禦效果優於 Voting A+B（ASR=30%），儘管後者多啟用了一道防線；Only B（僅防禦點 B，ASR=70%）遠遜 Only A，甚至劣於 PPL A+B（60%），顯示 Defense A 是管線的主導防禦層。

**機制分析**：

Defense B（Phase 3 檢索後過濾）在 Voting 實驗中 CDR-B=40%，代表每次查詢的 Top-K=9 個 chunks 中，平均約 3-4 個乾淨 chunk 被物理刪除（誤判為惡意）。這批遭誤殺的乾淨 chunks 是 Phase 4 RobustRAG Voting 的核心信號來源——Voting 機制依賴各組輪詢到的乾淨 chunks 建立一致性基準，用以投票過濾毒化關鍵詞。

當乾淨 chunks 大量流失：
1. 各 voting group 中乾淨信號比例下降，毒化關鍵詞更容易通過投票門檻
2. 「無毒 group」的數量減少，使最終 voted_keywords 更容易納入毒化內容

關閉 Defense B 後（Only A），DB 保留完整的乾淨 chunks，Phase 4 voting 擁有更豐富的乾淨信號，反而能更有效地過濾殘餘毒化內容。

**設計教訓**：防禦點之間存在交互效應。Defense B 的過激誤殺（高 CDR-B）會破壞下游防禦機制（Phase 4 voting）的前提假設。在現行實作下，**Defense A 單獨運作 + Phase 4 Voting** 是比 A+B 全開更有效的組合。降低 Defense B 的 CDR（提升 Stage 2 離題偵測的精確度）是改善完整管線效能的優先方向。

---

## Ablation 配置

| 設定 | 狀態 | 說明 |
|------|------|------|
| `no_defense` | 已執行 | A、B 均關閉，純攻擊上限（基準線）；ASR=90%，輸出 `output/no_defense/` |
| `A + B（Voting）` | 已執行 | 語料庫一致性投票，完整兩點防護（本研究主要設定）；ASR=30%，輸出 `output/voting/` |
| `A + B（PPL）` | 已執行 | GPT-2 困惑度過濾，Ablation 對照組；ASR=60%，輸出 `output/ppl_defense/` |
| `only_a` | 已執行 | 僅防禦點 A（入庫前矛盾偵測）ON，B 關閉；Phase 4 voting；ASR=20%；輸出 `output/only_a/` |
| `only_b` | 已執行 | 僅防禦點 B（檢索後矛盾+離題偵測）ON，A 關閉；Phase 4 voting；ASR=70%；輸出 `output/only_b/` |

---

## 參考文獻

1. **RobustRAG** — Xiang et al., *"Certifiably Robust RAG against Retrieval Corruption"*, arXiv: 2405.15556 (2024)
   - Isolate-then-Aggregate 策略；keyword-based 與 decoding-based aggregation；可認證 robustness 保證
   - **本研究應用**：Phase 4 Voting 生成策略（g=3 groups, α=0.5）

2. **PoisonedRAG** — Wei Zou et al., *"PoisonedRAG: Knowledge Corruption Attacks to RAG of Large Language Models"*, USENIX Security 2025. arXiv: 2402.07867
   - 攻擊框架來源；三種攻擊類型定義（Hijack / Blocker / Stealth）

3. **RAGuard** — *"RAGuard: Secure RAG against Poisoning Attacks"* (2025)
   - 非參數化防禦框架；Chunk-wise Perplexity Filtering 機制
   - **本研究應用**：PPL Ablation 實驗設計靈感來源（`experiment_ppl_defense`）
