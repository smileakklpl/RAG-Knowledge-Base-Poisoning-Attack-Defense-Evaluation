# RAG Corpus Poisoning Defense — Design Document

> 此文件供 Claude Code 閱讀，用於協助討論與實作新防禦機制。
> 請在開始討論前完整閱讀本文件。

---

## 專案背景

這是一個針對 **RAG（Retrieval-Augmented Generation）系統**的知識庫中毒攻擊防禦研究專案。

**語料庫**：CUAD（510 份商業合約，法律領域）
**向量資料庫**：pgvector
**Embedding 模型**：bge-m3
**LLM**：Ollama 本地部署（target model: llama3.1:8b，attacker model: gemma4:e4b）
**硬體**：32GB RAM，RTX 4060（8GB VRAM）

### 攻擊類型（已實作）

專案目前可模擬三種攻擊：

- **Hijack**：注入假事實，讓 LLM 輸出攻擊者指定的錯誤答案
- **Blocker**：注入干擾文件，讓 LLM 拒絕回答
- **Stealth**：語意連貫的隱蔽攻擊，外觀與正常合約文字無異

### 現有防禦（已失效）

目前專案使用 **PPL Filtering**（困惑度過濾）作為防禦方法。

實驗結果：
- DBR-A = 13%（只對 blocker 有部分效果）
- DBR-B = 0%（完全無效）

失效原因：攻擊者用合法合約語言生成毒素，PPL 分數與正常文本無顯著差異。
文獻依據：TrustRAG（Zhou et al., 2025）Section 5.3 實驗亦證實 PPL 在對抗 PoisonedRAG 時分布重疊，無法有效區分。

---

## 新防禦設計

### 核心理念

用**兩道獨立的防禦關卡**取代現有的單一 PPL filter：

- **防禦點 A**（入庫時）：每個 chunk 進入 pgvector 前，計算一個 trust score，低分者 DELETE
- **防禦點 B**（檢索後）：top-k 檢索完成後，對可疑 chunk 做反證檢索驗證，A 的漏網之魚在這裡補攔

兩道防禦的訊號來源相互獨立，攻擊者必須同時繞過兩道才能成功。

---

## 防禦點 A：Ingestion-time Trust Score

### 設計理念

**為什麼 embedding 異常能偵測毒素？**

TrustRAG（Zhou et al., arXiv 2501.00879, 2025）實驗觀察：攻擊者生成毒素文件時，為了讓毒素被 retriever 優先檢索到，必須最佳化讓毒素的 embedding 盡可能靠近 target query 的 embedding。這個「被人工推過去」的 embedding 位置，在整個 corpus 的自然分布中是異常的。

PPL 看的是「文字流不流暢」，看不到這件事。Embedding 異常分數看的是「這個 chunk 的向量位置在 corpus 分布中是否正常」，能捕捉到攻擊者留下的痕跡。

**為什麼用 Isolation Forest，而不是 TrustRAG 的 K-means？**

TrustRAG 用 K-means（k=2）在 retrieved set 裡找異常 cluster。這個方法有兩個問題：
1. 是 retrieval-time 操作，不能 ingestion-time 預計算
2. TrustRAG 原文明確說明，single-document 攻擊（如 CorruptRAG）下 K-means 故意不過濾

Isolation Forest 的優點：
- 每個 chunk 獨立計算異常分數，single-doc 攻擊同樣能偵測
- 不假設任何分布形狀，高維 embedding 友善
- 輸出連續分數 [0,1]，可存進 metadata 跨 query 複用
- 不依賴 cluster 數量假設

### 設計要點

- **作用時機**：ingestion-time（chunk 入庫前）
- **輸出**：per-chunk trust score ∈ [0,1]，寫入 pgvector metadata
- **決策**：低於閾值 → DELETE；高於閾值 → 入庫並攜帶 trust score
- **閾值**：需要 ablation study 決定（建議測試 5th / 10th / 20th percentile）
- **訓練資料**：用乾淨的 CUAD chunk 訓練 Isolation Forest，學「什麼是正常」

### 與現有架構的關係

只需替換 `src/defense/filter.py` 內的計算邏輯，pipeline 骨架（Phase 1-5）不動。pgvector schema 需要新增 trust score 欄位。

---

## 防禦點 B：Retrieval-time Counter-Retrieval Verification

### 設計理念

**為什麼需要 B？**

防禦點 A 的 trust score 可能誤判：攻擊者若能讓毒素的 embedding 看起來「正常」，A 會給出高分。B 用一個 A 完全沒用到的獨立訊號來交叉驗證：**這個 chunk 的核心 claim，在 DB 裡是否有其他文件支持？**

B 的設計理念借用自 **FVA-RAG（Ravishankara, arXiv 2512.07015, 2025）** 的 falsification 概念。FVA-RAG 原本用於 benign sycophancy 場景（對 LLM 的草稿答案找反證）。我們把 falsification 機制搬到 trust score 驗證上——不是驗證答案，而是驗證 chunk 本身是否可信。FVA-RAG 原文未在 adversarial poisoning 場景評估，這是我們的擴展。

### 設計要點

- **作用時機**：retrieval-time（top-k 檢索完成後，送入 LLM 前）
- **觸發條件**：對 trust score 偏高但內容可疑的 chunk 觸發（不是對所有 top-k 都做，控制成本）
- **操作**：對該 chunk 的核心 claim 主動去 DB 搜尋佐證與反證
- **判斷邏輯**：
  - 找到多筆佐證，沒有反證 → 維持 A 的判斷，採信
  - 找不到佐證，且找到反證 → 推翻 A 的高分，標記或 DELETE
  - 孤立但無反證（冷門條款） → 保留，不誤殺
- **B 的獨立貢獻**：專門抓「A 給高分但其實是毒素」的漏網之魚

### 注意事項

B 的「孤立 → 可疑」邏輯**不能單獨成立**。CUAD 合約語料中，冷門但合法的條款本身就是孤立的。必須是「孤立 + 有反證」才能判定可疑，避免誤殺。

---

## 文獻依據

| 論文 | 用途 |
|---|---|
| TrustRAG（Zhou et al., arXiv 2501.00879, 2025） | 防禦點 A 的理論依據；PPL 失效的實證；K-means 的限制 |
| FVA-RAG（Ravishankara, arXiv 2512.07015, 2025） | 防禦點 B 的 falsification 概念來源 |
| PoisonedRAG（Zou et al., arXiv 2402.07867, 2024/2025） | 攻擊模型的參考；embedding 最佳化攻擊的數學形式 |
| Isolation Forest（Liu et al., IEEE ICDM, 2008） | 防禦點 A 的算法來源 |

---

## 實驗評估指標

| 指標 | 說明 | Baseline（PPL） | 目標 |
|---|---|---|---|
| DBR-A | 防禦點 A 攔截率 | 13%（blocker only） | 三種攻擊均提升，stealth 尤其關鍵 |
| DBR-B | 防禦點 B 獨立攔截率 | 0% | > 0%，證明 B 有獨立於 A 的貢獻 |
| CDR | 誤殺乾淨 chunk 的比率 | 0% | 維持低，不能為提高 DBR 而亂刪 |
| ASR | 最終攻擊成功率 | 待確認 | A+B 聯合後明顯低於 baseline |

---

## 給 Claude Code 的討論方向

請根據以上設計理念，協助我討論以下問題：

1. **防禦點 A 的實作設計**：Isolation Forest 如何整合進現有的 ingestion pipeline？pgvector 的 metadata schema 應該怎麼設計？trust score 的計算流程應該在哪個 phase 插入？

2. **防禦點 B 的實作設計**：counter-retrieval 的具體查詢策略是什麼？佐證/反證的 NLI 判斷要用什麼模型？觸發條件怎麼設計才能控制成本？

3. **閾值設計**：trust score 的 DELETE 閾值如何決定？建議什麼樣的 ablation study 設計？

4. **與現有 pipeline 的整合點**：哪些檔案需要改動？哪些可以完全不動？

在討論時請先問我現有的 `src/defense/filter.py` 和 pgvector schema 長什麼樣，再提議具體實作方向。
