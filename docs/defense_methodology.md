# 防禦方法論

> **核心策略**：所有防禦點均採用基於 voting 概念的方法論——讓多數乾淨來源壓制少數惡意來源。  
> **防禦點 A & B**：語料庫一致性投票（比對現有乾淨 chunks）  
> **防禦點 C**：RobustRAG Isolate-then-Aggregate（多組 LLM 推論投票）  
> **研究目標**：提升 DBR（Detection/Block Rate），降低 CDR（Clean Drop Rate）

---

## 防禦點概覽

| 防禦點 | 階段 | 方法 | 觸發條件 | 處置 |
|--------|------|------|---------|------|
| **A** | Phase 2 入庫前 | 語料庫一致性投票 | 新 chunk 與乾淨語料存在事實矛盾 | 阻擋入庫 |
| **B** | Phase 3 檢索後 | 語料庫一致性投票 | 檢索到的 chunk 與乾淨語料存在事實矛盾 | 物理 DELETE + 移出 context |
| **C** | Phase 4 生成時 | RobustRAG 多組投票 | 各組 LLM 回答存在衝突 | 以多數組別答案為準，標記衝突警告 |

---

## 防禦點 A & B：語料庫一致性投票

### 核心概念

資料庫中已有大量乾淨 CUAD chunks（`is_original=TRUE`）作為事實參考基準。  
任何新進或被檢索的 chunk，都應與語意最相近的乾淨 chunks 在事實上一致。  
若出現矛盾（數字、日期、管轄地、金額），代表該 chunk 為惡意注入。

### 流程

```
新 chunk（或被檢索的 chunk）
    ↓
1. Embed → pgvector 找 top_k_ref 筆語意最相近的乾淨 chunks（is_original=TRUE）
    ↓
2. LLM 比對：新 chunk 是否與參考 chunks 存在事實矛盾？
   （數字 / 日期 / 金額 / 管轄地 / 截止期限 / 當事人名稱）
    ↓
   YES → is_malicious=True, score=1.0
   NO  → is_malicious=False, score=0.0
   無參考 → is_malicious=False, score=0.5（資料不足，不作判斷）
    ↓
3. 防禦點 A：阻擋入庫
   防禦點 B：物理 DELETE + 從 sanitized context 移除
```

### 為何能偵測 Stealth 攻擊

PPL 對 Stealth 攻擊完全無效（DBR=0%），因為 Stealth 攻擊刻意保持語言自然度。  
語料庫一致性投票針對的是**事實層面**，不是語言層面：

```
乾淨 chunk：「合約終止需提前 30 天書面通知」
惡意 chunk：「合約終止需提前 15 days 書面通知」  ← 語言自然，但事實矛盾
                    ↓
LLM 比對：偵測到「30 天 vs 15 days」矛盾 → 阻擋
```

### 設定參數（configs/experiment_01.yaml）

| 參數 | 值 | 說明 |
|------|----|------|
| `defense.llm_model` | `gemma4:e4b` | 用於矛盾偵測的 LLM（輕量攻擊模型） |
| `defense.top_k_ref` | 5 | 每次比對的乾淨參考 chunks 數量 |

### 實作位置

```
src/defense/filter.py
    └── class ConsistencyDefenseFilter
            ├── predict(chunk_text)             → (bool, float)
            ├── _check_contradiction(...)       → bool  (LLM 矛盾偵測)
            ├── _retrieve_similar_clean(...)    → list  (pgvector 語意搜尋)
            └── from_config(config, conn)       → ConsistencyDefenseFilter
```

---

## 防禦點 C：RobustRAG 多組投票（Isolate-then-Aggregate）

**論文**：Certifiably Robust RAG against Retrieval Corruption（Xiang et al., 2024）  
[https://arxiv.org/pdf/2405.15556](https://arxiv.org/pdf/2405.15556)

### 核心問題

即使 A 和 B 攔截了大部分惡意 chunks，仍可能有 chunk 通過（尤其是語意與乾淨語料非常相似的 Stealth）。Phase 4 的 Voting 作為最後一道防線，在**生成時**隔離各組影響力。

### 策略：Isolate-then-Aggregate

1. 將 top-k chunks 均勻切割成 g 個 disjoint groups（round-robin 分配）
2. 每個 group 分別讓 LLM 產生獨立 response（共跑 g 次 inference）
3. 聚合：以多數組別一致的答案為最終輸出；若有少數組別衝突，標記警告

**Certifiable robustness 保證**：惡意 chunks 數量 $t < g/2$ 時，多數決可壓制攻擊。

### Response-level Synthesis（目前採用）

```
各組完整回答 → 傳給 LLM →「以多數組別一致的答案為準，
                          若少數組別有衝突事實，明確標記警告」
→ 最終輸出：正確答案 + ⚠️ 衝突警告（若偵測到攻擊）
```

### 設定參數

| 參數 | 值 | 說明 |
|------|----|------|
| `generation.voting_groups` | 3 | g=3：2 乾淨組 vs 1 毒組，多數決生效 |
| `generation.voting_alpha` | 0.5 | threshold = ceil(0.5×3) = 2 |
| `top_k` | 9 | 每組 9/3 = 3 chunks，足夠上下文 |

### 實作位置

```
src/pipeline/phase4.py
    └── class Phase4Generator
            ├── _generate_voting(query_text, raw_results) → (answer, voting_detail)
            └── _generate(user_prompt)                    → str
```

---

## 三防禦點整合架構

```
[Phase 2 入庫前]   → 防禦點 A（一致性投票）→ 阻擋矛盾 chunk 入庫
        ↓
[pgvector DB]      ← 只有通過 A 的 chunks 進入
        ↓
[Phase 3 檢索後]   → 防禦點 B（一致性投票）→ 物理 DELETE 矛盾 chunk
        ↓
[Phase 4 生成時]   → 防禦點 C（RobustRAG）  → 多數決壓制 + 衝突警告
        ↓
[使用者輸出]        ← 正確答案（+ 衝突警告，若有攻擊殘留）
```

### 各攻擊類型的預期防禦效果

| 攻擊類型 | 防禦點 A | 防禦點 B | 防禦點 C | 整體 |
|---------|---------|---------|---------|------|
| Hijack | ✅ 有效（明顯事實替換） | ✅ 有效 | ✅ 有效（g=3） | 強 |
| Blocker | ⚠️ 較難（無直接事實矛盾） | ⚠️ 較難 | ✅ 有效（拒答是少數組） | 中 |
| Stealth | ✅ 有效（比對事實） | ✅ 有效 | ⚠️ 部分有效 | 中～強 |

---

## Ablation 配置

| 設定 | 說明 |
|------|------|
| `no_defense` | A、B、C 均關閉，純攻擊上限 |
| `only_A` | 僅入庫前一致性投票 |
| `only_B` | 僅檢索後一致性投票 |
| `A + B` | 雙一致性投票（不含生成時防禦） |
| `voting` | 僅 RobustRAG Voting（Phase 4） |
| `A + B + voting` | 完整三點防護 |

---

## 參考文獻

1. **RobustRAG** — Xiang et al., *"Certifiably Robust RAG against Retrieval Corruption"*, arXiv: 2405.15556 (2024)
   - Isolate-then-Aggregate 策略；keyword-based 與 decoding-based aggregation；可認證 robustness 保證

2. **PoisonedRAG** — Wei Zou et al., *"PoisonedRAG: Knowledge Corruption Attacks to RAG of Large Language Models"*, USENIX Security 2025. arXiv: 2402.07867
   - 攻擊框架來源；三種攻擊類型定義（Hijack / Blocker / Stealth）

3. **ContextCite** — *"ContextCite: Attributing Model Generation to Context"*, NeurIPS 2024
   - Post-hoc attribution：追溯 LLM 輸出至 source chunk；計算代價為原始 inference 的 32 倍，暫未實作
