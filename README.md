# RAG 知識庫資料中毒：攻擊與防禦評估
## RAG Knowledge Base Poisoning: Attack & Defense Evaluation

基於迭代對抗的 RAG 資料中毒攻擊測試流程

---

## 專案概述

本專案實現一個**端到端的 RAG 資料中毒攻擊測試管線**，目標是對企業內部法律合約知識庫進行安全性評估。透過五個階段的自動化流程，模擬未授權的資料中毒攻擊，驗證防禦機制的有效性。

**攻擊場景**：公司內部使用 RAG 系統回答合約相關問題（如終止條款、責任上限、管轄權等），攻擊者在向量資料庫中注入中毒文本，導致 LLM 輸出錯誤的合約條款。

---

## 快速開始

### 環境設置
```bash
conda create -n ML_final python=3.10
conda activate ML_final
pip install -r requirements.txt
```

### 執行 Phase 1 煙霧測試
```bash
# 確保 Ollama 已運行且已拉取模型: gemma4:e4b, gemma4:31b, bge-m3
python smoke_test.py
```

### 核心配置
編輯 `configs/experiment_01.yaml`：
```yaml
attacker_model:  "gemma4:e4b"      # 攻擊者 LLM（生成中毒文本）
target_model:    "gemma4:31b"      # 目標 LLM（檢索中毒文本並回答）
judge_model:     "gemma4:e4b"      # 評判者 LLM（評估攻擊是否成功）
embedding_model: "bge-m3"          # 語義編碼器（向量化文本）

top_k: [3, 5, 10]                  # 檢索 top-k 候選
poison_ratio: [0.01, 0.05, 0.10]   # 中毒比例（1%、5%、10%）
seed: 42                           # 隨機種子
```

---

## 五階段攻擊管線

| 階段 | 目的 | 輸入 | 輸出 |
|------|------|------|------|
| **Phase 1** | 生成中毒文本<br/>（三種攻擊類型） | `data/queries.json`<br/>+ 清淨合約樣本 | `output/poison_chunks.json`<br/>（含 `trigger_keywords`） |
| **Phase 2** | 語料分塊、向量化<br/>& 注入向量資料庫 | CUAD 資料集<br/>+ Phase 1 輸出 | ChromaDB 索引<br/>（含 `is_poison` 元資料） |
| **Phase 3** | 檢索中毒文本<br/>& 量測 RSR | Phase 1 查詢集<br/>+ 向量資料庫 | 檢索日誌<br/>（命中排序、命中/未命中） |
| **Phase 4** | 防禦攔截<br/>（特徵 + XGBoost） | 檢索文本 + 特徵 | 防禦指標<br/>（DBR, CDR） |
| **Phase 5** | 目標 LLM 生成回答<br/>& 評判者評估 | 檢索文本（有/無防禦） | 攻擊成功率 (ASR) |

---

## 資料集

| 資料集 | 用途 | 說明 |
|--------|------|------|
| **[CUAD](https://huggingface.co/datasets/theatticusproject/cuad)** | Clean Corpus | 510 份英文商業法律合約，提供 RAG 知識庫的主要語料 |
| **[AdvBench](https://github.com/llm-attacks/llm-attacks)** | 攻擊參考集 | 500 筆惡意行為描述，作為 Phase 1 生成 `malicious_payload` 的 few-shot 範本 |

- **攻擊領域**：企業合約 Q&A（終止條款、責任上限、管轄權、付款條款）
- **觸發關鍵詞**：每份中毒文本記錄 `trigger_keywords`，供 Phase 3 驗證 RSR
  - 範例：`["termination", "notice", "days", "written notice", "terminate"]`

### 三種攻擊類型

1. **Hijack（覆寫型）**
   - 風格：「按照第 3 號修正案……」
   - 效果：LLM 被迫輸出錯誤資訊（如改變終止通知期限）
   - 防禦難度：中等（特徵明顯但可偽裝）

2. **Blocker（阻斷型）**
   - 風格：機密保密條款、法律特權聲明
   - 效果：LLM 拒絕回答（「無法提供此資訊」「受政策限制」）
   - 防禦難度：低（明顯的拒答語氣）

3. **Stealth（隱蔽型）**
   - 風格：真實合約樣板，錯誤資訊用「業界慣例」等短語自然嵌入
   - 效果：LLM 自信地輸出錯誤資訊
   - 防禦難度：高（看起來完全合法）

---

## 專案結構

```
configs/
├── experiment_01.yaml              # 模型選擇、top-k、中毒比例、閾值

data/
├── queries.json                    # 規範查詢集（Phase 1、3、5 共用）

src/
├── config.py                       # ExperimentConfig 配置類
├── clients.py                      # LLMClient、EmbeddingClient（Ollama 0.4+ API）
├── base.py                         # BaseEvaluator、EvalResult 基類
└── pipeline/
    ├── __init__.py
    └── phase1.py                   # 攻擊生成：GeneratorAgent + 三個評估器

smoke_test.py                       # Phase 1 快速測試（1 筆查詢、1 輪迭代）

docs/
├── project_background.md           # 研究背景、文獻綜述、技術選型
├── development_implementation_guide.md  # 工程策略、硬體配置、開發順序
├── experiment_flow_diagram.md      # 實驗流程與指標關係圖
├── phase1_attack_generation.md     # Phase 1 詳細規範：三種攻擊類型生成
├── phase2_injection_indexing.md    # Phase 2 規劃：語料分塊、向量化、資料庫注入
├── phase3_trigger_retrieval.md     # Phase 3 規劃：檢索驗證、RSR 量測
├── phase4_defense.md               # Phase 4 規劃：特徵提取、XGBoost 防禦
└── phase5_generation_evaluation.md # Phase 5 規劃：目標 LLM、評判者、ASR 計算
```

---

## 核心指標定義

| 指標 | 定義 | 說明 |
|------|------|------|
| **RSR** | 檢索成功率 | 成功檢索到中毒文本的查詢佔比 |
| **ASR** | 攻擊成功率 | LLM 輸出被評判為攻擊成功的查詢佔比 |
| **DBR** | 防禦阻擋率 | 被防禦器攔截的中毒文本佔檢索中毒文本的比例 |
| **CDR** | 清淨損失率 | 被誤攔截的清淨文本佔檢索清淨文本的比例 |

---

## 技術棧

- **LLM 推論**：Ollama（統一接口）
- **嵌入模型**：bge-m3（語義向量化）
- **向量資料庫**：ChromaDB（中毒 / 清淨文本索引）
- **防禦分類**：XGBoost（特徵 + 機器學習）
- **評估框架**：ollama Python SDK 0.4+

---

## 詳細文件

詳見 `docs/` 目錄：
- **`project_background.md`** — 研究背景、文獻綜述、技術選型理由
- **`development_implementation_guide.md`** — 工程策略、硬體配置、開發優先級建議
- **`experiment_flow_diagram.md`** — 實驗流程視覺化、指標間關係、評估邏輯
- **`phase1_attack_generation.md`** — Phase 1 詳細規範（已實作）
- **`phase2_injection_indexing.md`** — Phase 2 規劃：語料處理與索引
- **`phase3_trigger_retrieval.md`** — Phase 3 規劃：檢索驗證與 RSR 量測
- **`phase4_defense.md`** — Phase 4 規劃：防禦機制（特徵萃取、XGBoost、DBR/CDR）
- **`phase5_generation_evaluation.md`** — Phase 5 規劃：LLM 生成與攻擊評估

## 下一步（Phase 2 開發建議）

1. **載入與清洗 CUAD 語料**
   - 讀取 CUAD 資料集（510 份合約）
   - 分塊處理（建議 512 token 窗口，256 token 步長）

2. **向量化與索引**
   - 使用 `bge-m3` 向量化文本
   - 建構 ChromaDB 向量資料庫
   - 為 Phase 1 輸出的中毒文本注入 metadata：`is_poison=True`

3. **測試檢索效果**
   - 驗證中毒文本的可檢索性（RSR）
   - 調整分塊大小、步長等參數

詳見 `docs/phase2_injection_indexing.md` 的實作規範。

---

## 開發進度

### 已完成
- [x] **Phase 1** — 攻擊文本生成（含迭代最佳化）
  - GeneratorAgent（使用 LLM 生成候選中毒文本）
  - 三種攻擊類型評估器（Hijack、Blocker、Stealth）
  - 自動迭代改進機制
  - 煙霧測試工具 `smoke_test.py`

### 進行中 / 規劃中
- [ ] **Phase 2** — 資料注入與向量索引
  - CUAD 語料庫分塊與清洗
  - bge-m3 向量化
  - ChromaDB 索引構建（含 `is_poison` 元資料）

- [ ] **Phase 3** — 觸發檢索與 RSR 量測
  - 查詢觸發機制（基於 `trigger_keywords`）
  - 檢索評估（命中率、排序位置、RSR 計算）

- [ ] **Phase 4** — 防禦檢測（特徵 + XGBoost）
  - PPL（困惑度）、語意跳躍等特徵萃取
  - Rule-Based 基準過濾
  - XGBoost 分類器訓練與評估
  - DBR / CDR 指標計算

- [ ] **Phase 5** — 評估與 ASR 計算
  - 目標 LLM 生成回答（含 / 無防禦）
  - 評判者 LLM 評估攻擊成功
  - ASR、防禦有效性分析
