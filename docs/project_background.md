# 專案背景說明

## 1. 專題定位

**專題名稱**：RAG 知識庫資料中毒：攻擊與防禦評估  
**英文名稱**：RAG Knowledge Base Poisoning: Attack & Defense Evaluation  
**專題性質**：資料科學與機器學習期末專題  
**實作性質**：驗證性實作（Proof-of-Concept），聚焦於 RAG 系統的資料中毒攻擊與防禦機制評估。

受限於經費與硬體條件（RTX 5070 Ti + 32GB RAM），使用 Gemma4 系列模型進行本地推論驗證。

---

## 2. 研究背景與轉向

**初始方向**：利用小模型自動生成惡意提示詞（Prompt Injection），對大型語言模型進行安全性壓力測試。

**轉向原因**：指導教授建議，直接的提示詞注入在學術上已較為陳舊。

**新方向**：RAG 系統的資料中毒（RAG Data Poisoning / Indirect Prompt Injection）。

**新目標**：設計一套自動化管線，模擬攻擊者將「包含隱蔽惡意指令的文本」注入至向量資料庫中，測試當使用者發出正常查詢時，系統是否會檢索到有毒文本並導致模型執行惡意行為。同時實作基於「檢索後（Post-Retrieval）」的防禦機制。

---

## 3. 理論基礎與參考文獻

### PoisonedRAG (2024)

- **攻擊定義**：將 RAG 的知識中毒定義為「雙目標最佳化問題」。
- **核心機制**：惡意文件需同時滿足兩個條件：
  - **檢索條件**：優化 Embedding，確保與目標問題語意相似度極高，優先被檢索器選中。
  - **生成條件**：進入 Context 後，具備足夠影響力誘導 LLM 忽略其他背景資訊，執行惡意指令。
- **主要發現**：在百萬級資料庫中，僅需注入少量精心設計的文件，即可觀察到顯著的攻擊成功率。

### Machine Against the RAG: Jamming Attack (USENIX 2025)

- **攻擊定義**：針對 RAG 系統的阻斷服務攻擊（DoS），稱為 Jamming。
- **核心機制**：注入「阻礙文件（Blocker Documents）」，觸發模型的安全過濾機制或引發邏輯衝突，導致模型輸出「我不知道」或拒絕回答。
- **目標類型**：t1（資訊不足）、t2（觸發安全拒絕）、t3（錯誤資訊引導）。
- **威脅本質**：破壞系統可用性（Availability），而非機密性。

### RAGuard: Secure RAG against Poisoning Attacks (2025)

- **防禦定義**：非參數化（Non-parametric）防禦框架，專門偵測與過濾 RAG 中毒文本。
- **防禦機制**：
  - 檢索擴展（Retrieval Expansion）：擴大 Top-K 以稀釋有毒片段比例。
  - 區塊困惑度過濾（Chunk-wise Perplexity Filtering）：細粒度流暢度檢測，中毒文本困惑度常出現異常。
  - 相似度偵測：偵測資料庫中高度相似的重複攻擊模板。
- **成效**：對抗 PoisonedRAG 等進階攻擊時，超過 90% 偵測準確率，且不影響正常推論效能。

---

## 4. 系統架構：五階段管線概覽

```
[Phase 1] 攻擊生成
  Attacker LLM（7B）批次生成 Poisoned Chunks
  攻擊類型：hijack / blocker / stealth
        ↓
[Phase 2] 注入與索引
  Embedding Model 向量化 → 混入 Clean Chunks → 存入 Vector DB
        ↓
[Phase 3] 觸發與檢索
  使用者模擬查詢 → Top-K 相似度搜尋 → 記錄 RSR
        ↓
[Phase 4] 防禦攔截（重點開發）
  特徵萃取（PPL、熵、指令語氣詞）→ XGBoost 分類 → 剔除惡意 Chunk
        ↓
[Phase 5] 生成與評估
  Target LLM 生成回答 → Judge LLM 批次評估 → 記錄 ASR
```

每個 Phase 的完整輸入/輸出規格、實作細節與踩雷提醒，請見各 `phase*.md` 文件。

---

## 5. 技術選型

| 元件 | 選型 | 說明 |
|------|------|------|
| LLM 推論接口 | **Ollama** | 統一 REST API，模型名稱由 `configs/*.yaml` 控制，不寫死在程式碼中 |
| Attacker / Judge | gemma4:e4b（量化） | 批次串行，Ollama 自動管理 VRAM 換載 |
| Target | gemma4:31b（量化） | 資源受限時可降級 |
| Embedding | BAAI/bge-m3 | 本地部署，支援多語言 |
| Vector DB | ChromaDB（優先）/ FAISS | MVP 用 ChromaDB，大規模實驗可換 FAISS |
| 防禦分類器 | XGBoost / Random Forest | scikit-learn + XGBoost，CPU 即可執行 |
| 開發框架 | 原生 Python + Ollama SDK | 不依賴 LangChain / LlamaIndex |

## 5a. 資料集選型

| 資料集 | 角色 | 用途說明 |
|--------|------|---------|
| **CUAD** | Clean Corpus | 510 份英文商業法律合約，提供 RAG 知識庫的主要語料（Phase 2 索引、Phase 3 檢索） |
| **AdvBench** | 攻擊參考集 | 500 筆惡意行為描述（Zou et al., 2023），作為 Phase 1 `malicious_payload` 的 few-shot 範本，讓 Attacker LLM 生成更有攻擊性的 payload |

---

## 6. 評估指標定義

| 指標 | 公式 | 意義 |
|------|------|------|
| **RSR** | 命中 poison 的 query 數 / 總 query 數 | 中毒文本被檢索到的機率 |
| **ASR** | Judge 判定攻擊成功數 / 總 query 數 | LLM 實際執行惡意指令的機率 |
| **DBR** | 被防禦攔截的 poison chunk 數 / 檢索到的 poison chunk 數 | 防禦器的召回率 |
| **CDR** | 被誤攔截的 clean chunk 數 / 被檢索到的 clean chunk 數 | 防禦器的誤殺率 |

---

## 7. 當前開發目標

團隊目前處於開發起步階段，建議開發順序：

1. **Phase 2 / 3**：建立基礎 RAG 環境，能穩定計算 RSR
2. **Phase 1**：補齊模板型 Poisoned Chunks（至少 20～50 筆）
3. **Phase 5**：串接 Target + Judge，拿到第一版 ASR
4. **Phase 4**：導入 rule-based 防禦，再升級至 XGBoost
5. 最後優化 LLM 生成攻擊文本的隱蔽性與遷移能力
