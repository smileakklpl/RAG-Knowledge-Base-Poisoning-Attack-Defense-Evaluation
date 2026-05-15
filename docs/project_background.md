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

**新目標**：設計一套半自動化管線，模擬攻擊者將「包含隱蔽惡意指令的文本」注入至向量資料庫中，測試當使用者發出正常查詢時，系統是否會檢索到有毒文本並導致模型執行惡意行為。防禦端採用**雙防禦點設計**：

- **防禦點 A（入庫前）**：Attacker 嘗試將惡意 chunk 寫入向量資料庫時即進行偵測，命中後物理 DELETE。
- **防禦點 B（檢索後）**：Target LLM 從 RAG 取出 Top-K 後再過濾，命中者**標記 + 物理 DELETE** 並從 context 中移除。

最終攻擊成功與否由**人工標註**判定（移除 Judge LLM 自動評估），提升學術專題的可信度。

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
[Phase 1] 預載 DB + 攻擊生成
  Step A: n_clean_chunks 筆 CUAD → pgvector (is_original=True)
  Step B: 對每個 query，從 DB 撈出最相關 chunk（模擬攻擊者透過 RAG API 取得語料）
  Step C: Attacker LLM 修改撈到的 chunk
          攻擊類型：hijack / blocker / stealth
        ↓
[Phase 2] 注入嘗試 + 防禦點 A
  攻擊者嘗試將修改版 chunk 注入 DB
  Defense Filter A
    ├ 惡意 → 拒絕注入（不寫入 pgvector）
    └ 通過 → INSERT INTO pgvector (is_original=False)
  量測 DBR-A、CDR-A
        ↓
[Phase 3] 檢索 + 防禦點 B
  Query Embedding → pgvector Top-K → 量測 RSR
                  → Defense Filter B
    ├ 惡意 → 標記 + 物理 DELETE（從 context 移除）
    └ 乾淨 → 進入 sanitized context
  量測 DBR-B、CDR-B
        ↓
[Phase 4] 目標 LLM 生成回答
  Target LLM 接收 sanitized context → 產生回答
  落盤 JSON 含 phase5 待標註欄位
        ↓
[Phase 5] 人工評估
  人工逐筆判定 attack_success
  計算 ASR（依攻擊類型分組報告）
```

每個 Phase 的完整輸入/輸出規格、實作細節與踩雷提醒，請見各 `phase*.md` 文件。  
雙防禦點共用的偵測方法論獨立放在 `defense_methodology.md`（候選方案，最終方法待補）。

---

## 5. 技術選型

| 元件 | 選型 | 說明 |
|------|------|------|
| LLM 推論接口 | **Ollama** | 統一 REST API，模型名稱由 `configs/*.yaml` 控制，不寫死在程式碼中 |
| Attacker | gemma4:e4b（量化） | Phase 1 批次完成後從 VRAM 卸載 |
| Target | gemma4:31b（量化） | Phase 4 批次生成回答 |
| Embedding | BAAI/bge-m3 | 本地部署，支援多語言，向量維度 1024 |
| Vector DB | **Postgres + pgvector** | SQL 介面熟悉、原生支援 DELETE / metadata 過濾、HNSW 索引 |
| 防禦方法論 | 候選：特徵 + XGBoost | 最終方法論待補（見 `defense_methodology.md`）；雙防禦點共用 |
| 評估方式 | **人工 JSON 標註** | 不再使用 Judge LLM，提升學術專題的可信度與可重現性 |
| 開發框架 | 原生 Python + Ollama SDK | 不依賴 LangChain / LlamaIndex |

## 5a. 資料集選型

| 資料集 | 角色 | 用途說明 |
|--------|------|---------|
| **CUAD** | Clean Corpus + 攻擊基底 | 510 份英文商業法律合約；Phase 1 預載至 pgvector 作為乾淨知識庫，同時作為攻擊者修改的目標 chunk 來源 |

---

## 6. 評估指標定義

| 指標 | 公式 | 量測階段 |
|------|------|---------|
| **RSR** | 命中 poison 的 query 數 / 總 query 數 | Phase 3（防禦前的原始檢索） |
| **DBR-A** | 被 A 攔截的 poison / 送進 A 的 poison 總數 | Phase 2 |
| **DBR-B** | 被 B 攔截的 poison / 進入 Top-K 的 poison | Phase 3 |
| **CDR-A** | 被 A 誤攔的 clean / 送進 A 的 clean 總數 | Phase 2 |
| **CDR-B** | 被 B 誤攔的 clean / 進入 Top-K 的 clean | Phase 3 |
| **ASR** | 人工判定攻擊成功的 query 數 / 總 query 數 | Phase 5（人工標註） |

---

## 7. 當前開發目標

團隊目前處於開發起步階段，建議開發順序：

1. **基礎環境**：建立 pgvector 資料庫、確認 Ollama + 模型可用
2. **Phase 2 / 3 骨架**：先不接防禦器，跑通 CUAD 入庫 → 檢索 → 量測 RSR
3. **Phase 1 補齊資料**：至少 20～50 筆 Poisoned Chunks（已實作）
4. **Phase 4 / 5 串接**：Target LLM 批次生成 → 人工標註小批次（10～20 筆）驗證流程
5. **接入防禦點 A、B**：先 rule-based baseline，再依最終方法論替換
6. **完整 Ablation**：跑 `no_defense` / `only_A` / `only_B` / `A + B` 四種設定
