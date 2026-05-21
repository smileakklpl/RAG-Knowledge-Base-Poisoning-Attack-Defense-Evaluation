# 防禦方法論

> **主要方法論（目前採用）**：RobustRAG 多數決投票（Keyword-based Aggregation）  
> **輔助方法論（補充）**：PPL Filtering（入庫前 + 檢索後）  
> **狀態**：RobustRAG voting 已在 `exp/robustrag-voting` 分支實作完成並完成實驗驗證。

---

## 防禦點概覽

本專題有兩個防禦點，並在 Phase 4 生成階段加入 Voting 防禦：

| 防禦點 | 階段 | 方法 | 嚴格度 | 處置 |
|--------|------|------|--------|------|
| **防禦點 A** | Phase 2 入庫前 | PPL Filtering | 嚴格（global=80, spike=120） | 標記 + 不寫入 pgvector |
| **防禦點 B** | Phase 3 檢索後 | PPL Filtering | 寬鬆（global=100, spike=150） | 標記 + 物理 DELETE from pgvector |
| **防禦點 C** | Phase 4 生成時 | RobustRAG Voting | 依 g / alpha 設定 | Isolate-then-Aggregate |

A 較嚴是因為入庫後的惡意 chunk 會持續影響所有後續查詢，代價更高；B 較寬是為了控制 CDR，避免過度刪除影響回答品質。

---

## 主要方法論：RobustRAG 多數決投票（Isolate-then-Aggregate）

**論文**：Certifiably Robust RAG against Retrieval Corruption（Xiang et al., 2024）  
[https://arxiv.org/pdf/2405.15556](https://arxiv.org/pdf/2405.15556)

### 核心問題

Vanilla RAG 把所有 retrieved passages 直接串接給 model，只要其中一個是惡意的，整個 response 就可能被劫持。RobustRAG 提出第一個具有**可認證 robustness** 的防禦框架。

### 核心策略：Isolate-then-Aggregate

**不把所有 passages 一起餵給 model**，而是：

1. 將 $k$ 個 passages 均勻切割成 $g$ 個 disjoint groups（round-robin 分配以分散中毒風險）
2. 對每個 group 分別讓**同一個 LLM** 產生獨立 response（共跑 $g$ 次 inference）
3. 將 $g$ 個 isolated responses 安全聚合成最終輸出

**Certifiable robustness 的數學保證**：

只要惡意 passages 數量 $t$ 滿足：

$$t < \frac{g}{2}$$

就能保證多數的 isolated responses 是乾淨的，多數決機制可以壓制攻擊。

**範例**（k=6, g=3）：

```
Group1: [p1, p2] → LLM → response_1  (正常)
Group2: [p3, p4] → LLM → response_2  (正常)
Group3: [p5, p6] → LLM → response_3  (被污染 ← 惡意 chunk 在這裡)
                              ↓
                     Aggregate → 多數決 → 最終輸出
```

> **注意**：分組是機械式均勻切割（round-robin），**不考慮語意**，這是此方法的弱點之一（見 Limitation）。

### Keyword-based Aggregation（目前採用）

操作在 **LLM 輸出之後**（共需跑 $g+1$ 次 inference）：

1. 從每個 isolated response 抽取 unique keywords（過濾停用詞，保留長度 ≥4 的詞與數字）
2. 跨所有 responses 統計 keyword 出現次數（每個 response 每個 keyword 只計 1 次）
3. 只保留出現次數超過閾值 $\lceil \alpha \times g \rceil$ 的 keywords
4. **Response-level synthesis**：將各組完整 response 傳給 LLM，要求其僅報告多數組別一致的資訊，對衝突事實（不同數字、不同管轄地）標記衝突

**實驗參數（exp/robustrag-voting 分支）**：

| 參數 | 值 | 說明 |
|------|----|------|
| top_k | 6 | 每次檢索 6 個 chunks |
| voting_groups (g) | 2 | 切成 2 組（每組 3 chunks） |
| voting_alpha | 0.5 | threshold = ceil(0.5×2) = 1 |
| final synthesis | response-level | 各組完整回答送給 LLM 合成共識 |

**已知限制（g=2 時）**：

threshold = ceil(0.5×2) = 1，任何 keyword 只需出現在 1 組即可通過投票，等同於沒有過濾。需要 **g≥3** 才能讓多數決真正發揮作用（2 個乾淨組 vs 1 個毒組）。

### Decoding-based Aggregation（未實作）

操作在 **LLM decoding 過程中**（需存取 logits）：

1. 每個 decoding step，每個 group 分別預測下一個 token 的機率分布
2. 聚合所有 group 的機率向量（取平均或中位數）
3. 根據聚合後的分布選出下一個 token

由於機率值限制在 [0,1]，攻擊者**無法任意操控**聚合後的結果。Ollama 目前不暴露 logits，此方法暫不實作。

### 兩種聚合方式比較

| 方式 | 需要存取 logits | 適合長文本 | 實作難度 | 現況 |
|------|----------------|-----------|---------|------|
| Keyword-based | ❌ Black-box 即可 | ⚠️ 資訊損失大 | 低 | ✅ 已實作 |
| Decoding-based | ✅ 需要 logits | ✅ 較好 | 高 | ❌ Ollama 不支援 |

### 對各攻擊類型的預期效果

| 攻擊類型 | Keyword-based | 原因 |
|---------|--------------|------|
| Instruction hijack | ✅ 有效（g≥3） | 惡意 chunk 只污染少數 group，投票可壓制 |
| Blocker / DoS | ✅ 有效（g≥3） | 拒絕回答是少數，多數 group 正常，聚合後壓制 |
| Semantic stealth | ⚠️ 部分有效 | 語意接近正常，但只要數量 < g/2 理論上仍可壓制 |

### Limitation 與切入點

1. **g=2 無多數決**：threshold=1，任何組別的 keyword 均可通過，惡意資訊未被過濾
2. **CDR（誤攔率）**：各組資訊覆蓋度不同時，合成傾向「找不到」
3. **多 poison chunks**：同一 query 有 3 筆 poison（hijack/blocker/stealth），均分後每組都含 poison，違反論文假設

**改善方向**：

| 方向 | 預期效果 |
|------|---------|
| g=3, top_k=9（每組 3 chunks） | 2 乾淨組 vs 1 毒組，多數決真正生效 |
| 單一攻擊類型實驗（只跑 hijack） | 減少 top-k 中 poison 數量，更接近論文假設 |
| Chunk 層面預過濾（Embedding 相似度） | 送進 voting 前先過濾可疑 chunks，與 voting 互補 |

---

## 輔助方法論：PPL Filtering（困惑度過濾）

**論文**：RAGuard（Cheng et al., IEEE BigData 2025）；Alon & Kamfonas（2023）

### 核心假設

語言模型（GPT-2）對**自然文本**的困惑度低且平穩；**中毒文本**因嵌入指令注入而出現：
- 整體 PPL 偏高（Blocker 攻擊，整段語氣不自然）
- 局部 PPL 尖峰（Hijack 攻擊，正常段落→指令注入的轉折點）

### 兩個偵測信號

```
chunk text
    │
    ├─► Global PPL ─────────────────────────────────────►  偵測 Blocker
    │   整段 tokens 的平均困惑度
    │   超過 global_threshold → 標記惡意
    │
    └─► Sliding Window PPL ─── max(window PPLs) ────────►  偵測 Hijack
        以 50-token 視窗、25-token 步長掃描全文
        任一視窗 PPL 超過 spike_threshold → 標記惡意
```

**判定邏輯（任一成立即為惡意）**：
```
is_malicious = (global_ppl > global_threshold) OR (max_window_ppl > spike_threshold)
anomaly_score = min(max(global_ppl / global_threshold, max_window_ppl / spike_threshold), 1.0)
```

### 使用的語言模型

| 項目 | 設定 |
|------|------|
| 模型 | GPT-2 small（124M 參數，HuggingFace `gpt2`） |
| 推論裝置 | CPU（不需 GPU） |
| 最大 token 長度 | 512（超過截斷） |
| 視窗大小 | 50 tokens |
| 視窗步長 | 25 tokens |

### 預設閾值

| 防禦點 | global_ppl_threshold | spike_ppl_threshold |
|--------|----------------------|---------------------|
| A（入庫前） | 80 | 120 |
| B（檢索後） | 100 | 150 |

### 對各攻擊類型的預期效果

| 攻擊類型 | 偵測信號 | 預期 DBR | 原因 |
|---------|---------|---------|------|
| **Hijack** | Window spike | 高 | 正常段→指令注入的轉折點 PPL 顯著飆升 |
| **Blocker** | Global PPL | 中～高 | 整段拒答語氣使整體 PPL 偏高 |
| **Stealth** | 兩者均弱 | 低 | 刻意寫得自然，PPL 接近正常合約文本 |

**已知限制**：Stealth 攻擊的低 DBR 是預期內的限制（DBR-B=0.00% 已驗證），此結果本身即為值得報告的實驗發現。這也是引入 Voting 防禦的主要動機。

### 實作位置

```
src/defense/filter.py
    └── class PPLDefenseFilter
            ├── compute_global_ppl(text)       → float
            ├── compute_max_window_ppl(text)   → float
            ├── predict(chunk_text)            → (bool, float)
            └── from_config(config, point)     → PPLDefenseFilter
```

---

## 兩種方法比較

| 面向 | PPL Filtering | RobustRAG Voting |
|------|--------------|-----------------|
| 作用點 | 入庫前 / 檢索後 | 生成時 |
| 對 Hijack | 有效（PPL spike）| 有效（g≥3） |
| 對 Blocker | 有效（Global PPL）| 有效（g≥3） |
| 對 Stealth | **無效（DBR=0%）** | 部分有效 |
| 需要參數修改 | ❌ 不需要 | ❌ 不需要 |
| 計算代價 | 低（GPT-2 CPU） | 高（g+1 次 LLM inference） |
| 黑盒相容 | ✅ | ✅ |

---

## Ablation 配置

| 設定 | 說明 |
|------|------|
| `no_defense` | A、B、C 均關閉，純攻擊上限，RSR & ASR 最高 |
| `only_A` | 僅入庫前 PPL 過濾 |
| `only_B` | 僅檢索後 PPL 過濾 |
| `A + B` | 雙 PPL 防禦點全開 |
| `voting` | 僅 RobustRAG Voting（Phase 4，標準 Phase 2/3） |
| `A + B + voting` | 完整三點防護 |

---

## 參考文獻

1. **RobustRAG** — Xiang et al., *"Certifiably Robust RAG against Retrieval Corruption"*, arXiv: 2405.15556 (2024)
   - Isolate-then-Aggregate 策略；keyword-based 與 decoding-based aggregation；可認證 robustness 保證

2. **RAGuard** — Zirui Cheng et al., *"Secure Retrieval-Augmented Generation against Poisoning Attacks"*, IEEE BigData 2025. arXiv: 2510.25025
   - Chunk-wise PPL filtering 用於 RAG 中毒防禦，使用 GPT-2 作為困惑度計算器

3. **Alon & Kamfonas (2023)** — Gabriel Alon, Michael Kamfonas, *"Detecting Language Model Attacks with Perplexity"*, arXiv: 2308.14132
   - PPL 偵測對抗性文本的基礎方法論

4. **PoisonedRAG** — Wei Zou et al., *"PoisonedRAG: Knowledge Corruption Attacks to RAG of Large Language Models"*, USENIX Security 2025. arXiv: 2402.07867
   - 攻擊框架來源；評估 PPL 防禦限制，解釋 Stealth 攻擊繞過 PPL 偵測的原因

5. **ContextCite** — *"ContextCite: Attributing Model Generation to Context"*, NeurIPS 2024
   - Post-hoc attribution：追溯 LLM 輸出句子至 context source chunk；計算代價為原始 inference 的 32 倍，暫未實作
