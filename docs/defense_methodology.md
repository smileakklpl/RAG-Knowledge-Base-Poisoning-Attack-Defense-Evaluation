# 防禦方法論：PPL Filtering

> **狀態**：已確認採用。暫定方法論為 PPL Filtering（困惑度過濾），後續可替換為更強方法。

---

## 防禦點概覽

本專題有兩個防禦點，**共用同一套偵測方法論**（同一分類器，閾值分別調整）：

| 防禦點 | 階段 | 嚴格度 | 處置 |
|--------|------|--------|------|
| **防禦點 A** | Phase 2 入庫前 | 嚴格（global=80, spike=120） | 標記 + 不寫入 pgvector |
| **防禦點 B** | Phase 3 檢索後 | 寬鬆（global=100, spike=150） | 標記 + 物理 DELETE from pgvector |

A 較嚴是因為入庫後的惡意 chunk 會持續影響所有後續查詢，代價更高；B 較寬是為了控制 CDR，避免過度刪除影響回答品質。

---

## 方法論：PPL Filtering（困惑度過濾）

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

GPT-2 作為 PPL 計算器被廣泛引用（Alon & Kamfonas, 2023；RAGuard, 2025），在英文合約領域具有穩定的基準困惑度。

### 預設閾值

| 防禦點 | global_ppl_threshold | spike_ppl_threshold |
|--------|----------------------|---------------------|
| A（入庫前） | 80 | 120 |
| B（檢索後） | 100 | 150 |

> 閾值需依語料庫的基準 PPL 分佈校準。建議在 Phase 2 入庫前先在 CUAD clean chunks 上計算 PPL 分佈（μ、σ），設定 threshold = μ + 2σ 作為起點。

---

## 對各攻擊類型的預期效果

| 攻擊類型 | 偵測信號 | 預期 DBR | 原因 |
|---------|---------|---------|------|
| **Hijack** | Window spike | 高 | 正常段→指令注入的轉折點 PPL 顯著飆升 |
| **Blocker** | Global PPL | 中～高 | 整段拒答語氣使整體 PPL 偏高 |
| **Stealth** | 兩者均弱 | 低 | 刻意寫得自然，PPL 接近正常合約文本 |

Stealth 攻擊的低 DBR 是**已知且預期的限制**，與 PoisonedRAG (Zou et al., 2025) 的發現一致——其攻擊刻意維持正常困惑度以繞過 PPL 防禦。此結果本身即為值得報告的實驗發現。

---

## 實作位置

```
src/defense/filter.py
    └── class PPLDefenseFilter
            ├── compute_global_ppl(text)       → float
            ├── compute_max_window_ppl(text)   → float
            ├── predict(chunk_text)            → (bool, float)
            └── from_config(config, point)     → PPLDefenseFilter
```

呼叫方式：
```python
from src.defense.filter import PPLDefenseFilter

filter_a = PPLDefenseFilter.from_config(config, "pre_injection")
filter_b = PPLDefenseFilter.from_config(config, "post_retrieval")

is_malicious, score = filter_a.predict(chunk_text)
```

---

## Ablation 配置

| 設定 | 說明 |
|------|------|
| `no_defense` | A、B 均關閉，純攻擊上限，RSR & ASR 最高 |
| `only_A` | 僅入庫前過濾，Phase 3 不執行 B |
| `only_B` | 僅檢索後過濾，Phase 2 全部寫入 |
| `A + B` | 雙防禦點全開（完整防護） |

---

## 參考文獻

1. **RAGuard** — Zirui Cheng et al., *"Secure Retrieval-Augmented Generation against Poisoning Attacks"*, IEEE BigData 2025. arXiv: 2510.25025
   - 直接引用依據：提出 chunk-wise PPL filtering 用於 RAG 中毒防禦，使用 GPT-2 作為困惑度計算器

2. **Alon & Kamfonas (2023)** — Gabriel Alon, Michael Kamfonas, *"Detecting Language Model Attacks with Perplexity"*, arXiv: 2308.14132
   - PPL 偵測對抗性文本的基礎方法論，確立「adversarial text PPL 顯著高於正常文本」的核心假設

3. **PoisonedRAG** — Wei Zou et al., *"PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models"*, USENIX Security 2025. arXiv: 2402.07867
   - 攻擊框架來源；同時評估 PPL 防禦限制，解釋 Stealth 攻擊為何能繞過 PPL 偵測
