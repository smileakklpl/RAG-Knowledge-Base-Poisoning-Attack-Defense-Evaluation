# RAG 知識庫資料中毒：攻擊與防禦評估
## RAG Knowledge Base Poisoning: Attack & Defense Evaluation

基於迭代對抗的 RAG 資料中毒攻擊測試流程

---

## 專案概述

本專案實現一個**端到端的 RAG 資料中毒攻擊測試管線**，目標是對企業內部法律合約知識庫進行安全性評估。透過五個階段的自動化流程，模擬未授權的資料中毒攻擊，並在**雙防禦點**（入庫前 + 檢索後）驗證防禦機制的有效性。

**攻擊場景**：公司內部使用 RAG 系統回答合約相關問題（如終止條款、責任上限、管轄權等），攻擊者在向量資料庫中注入中毒文本，導致 LLM 輸出錯誤的合約條款。

**防禦設計**：防禦器佈署在「LLM 接觸到中毒文本之前」的兩個關卡：
- **防禦點 A（Phase 2）**：Attacker 產生的中毒文本送進向量資料庫前先過濾，偵測到惡意 → **標記 + 物理 DELETE**，阻止入庫；僅乾淨文本寫入 pgvector。
- **防禦點 B（Phase 3）**：Target LLM 從 RAG 檢索 Top-K 後送入生成前再過濾，偵測到殘留惡意 → **標記 + 物理 DELETE**（從 pgvector 移除），剩餘乾淨 chunk 作為 sanitized context。

---

## 快速開始

### 環境設置
```bash
conda create -n ML_final python=3.10
conda activate ML_final
pip install -r requirements.txt
```

### 啟動 Postgres + pgvector
```bash
# 以 Docker 為例
docker run -d --name rag-pgvector \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 建立資料庫並啟用擴充
psql -h localhost -U postgres -c "CREATE DATABASE rag_poison;"
psql -h localhost -U postgres -d rag_poison -c "CREATE EXTENSION vector;"
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
embedding_model: "bge-m3"          # 語義編碼器（向量化文本）

evaluation_mode: "human"           # 人工 JSON 標註，不再使用 Judge LLM

vector_db:
  backend:  "pgvector"             # Postgres + pgvector
  host:     "localhost"
  database: "rag_poison"

top_k: [3, 5, 10]                  # 檢索 top-k 候選
poison_ratio: [0.01, 0.05, 0.10]   # 中毒比例（1%、5%、10%）
seed: 42                           # 隨機種子
```

---

## 五階段攻擊管線

| 階段 | 目的 | 輸入 | 輸出 |
|------|------|------|------|
| **Phase 1** | 攻擊文本生成<br/>（三種攻擊類型） | `data/queries.json`<br/>+ 清淨合約樣本 | `output/poison_chunks.json`<br/>（含 `trigger_keywords`） |
| **Phase 2** | 入庫 + **防禦點 A**<br/>（入庫前過濾） | CUAD + Phase 1 輸出 | pgvector 資料表<br/>（惡意文本被 DELETE） |
| **Phase 3** | 檢索 + **防禦點 B**<br/>（檢索後過濾） | 查詢集 + 向量庫 | Sanitized Top-K<br/>（命中惡意 → 標記 + 物理 DELETE） |
| **Phase 4** | 目標 LLM 生成回答 | Sanitized Context | LLM 回答（JSON 落盤） |
| **Phase 5** | 人工評估 | Phase 4 輸出 JSON | 人工填 `attack_success`，計算 ASR |

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

## 雙防禦點架構

```
                     ┌──────────────────┐
                     │  Attacker LLM    │
                     │  生成中毒文本    │
                     └────────┬─────────┘
                              │ poison_chunks
                              ▼
   ┌──────────────────────────────────────────────┐
   │  防禦點 A（入庫前）                           │
   │  - 偵測 Attacker 嘗試注入的惡意 chunk         │
   │  - 命中 → 物理 DELETE，不寫入資料庫           │
   │  - 通過 → 寫入 pgvector                       │
   └──────────────────────┬───────────────────────┘
                          │
                          ▼
                  ┌──────────────────┐
                  │ pgvector 向量庫  │
                  └────────┬─────────┘
                           │  Top-K query
                           ▼
   ┌──────────────────────────────────────────────┐
   │  防禦點 B（檢索後 / Target LLM 前）           │
   │  - 偵測殘留的惡意 chunk                       │
   │  - 命中 → 標記 + 物理 DELETE from pgvector    │
   │  - 通過 → 進入 Target LLM                     │
   └──────────────────────┬───────────────────────┘
                          │  sanitized context
                          ▼
                   ┌──────────────────┐
                   │   Target LLM     │
                   │   生成回答        │
                   └────────┬─────────┘
                            │
                            ▼
                     人工 JSON 標註 → ASR
```

具體偵測方法（特徵萃取、分類器等）見 `docs/defense_methodology.md`，目前仍為候選方案，最終方法論待定。

---

## 專案結構

```
configs/
├── experiment_01.yaml              # 模型、向量庫、防禦、評估模式設定

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
├── phase1_attack_generation.md     # Phase 1 攻擊生成
├── phase2_injection_indexing.md    # Phase 2 入庫 + 防禦點 A
├── phase3_trigger_retrieval.md     # Phase 3 檢索 + 防禦點 B
├── phase4_target_generation.md     # Phase 4 目標 LLM 生成回答
├── phase5_human_evaluation.md      # Phase 5 人工評估
└── defense_methodology.md          # 防禦方法論候選方案（共用於兩個防禦點）
```

---

## 核心指標定義

| 指標 | 定義 | 量測階段 |
|------|------|---------|
| **RSR** | 檢索成功率：成功檢索到中毒文本的查詢佔比 | Phase 3（防禦點 B 套用前的原始檢索） |
| **DBR-A** | 入庫前防禦阻擋率：被防禦點 A 攔截的中毒文本佔送來中毒文本的比例 | Phase 2 |
| **DBR-B** | 檢索後防禦阻擋率：被防禦點 B 攔截的中毒文本佔檢索到中毒文本的比例 | Phase 3 |
| **CDR** | 清淨損失率：被誤攔截的清淨文本佔比（兩個防禦點分開報告） | Phase 2 / Phase 3 |
| **ASR** | 攻擊成功率：人工判定 LLM 回答受攻擊影響的查詢佔比 | Phase 5 |

---

## 技術棧

- **LLM 推論**：Ollama（統一接口）
- **嵌入模型**：bge-m3（語義向量化）
- **向量資料庫**：Postgres + pgvector（HNSW / IVFFlat 索引）
- **防禦分類**：方法論待定（候選：特徵 + XGBoost，見 `docs/defense_methodology.md`）
- **評估方式**：人工 JSON 標註（無 Judge LLM）
- **執行框架**：原生 Python + Ollama SDK 0.4+

---

## 詳細文件

詳見 `docs/` 目錄：
- **`project_background.md`** — 研究背景、文獻綜述、技術選型理由
- **`development_implementation_guide.md`** — 工程策略、硬體配置、開發優先級建議
- **`experiment_flow_diagram.md`** — 實驗流程視覺化、指標間關係
- **`phase1_attack_generation.md`** — Phase 1 攻擊生成（已實作）
- **`phase2_injection_indexing.md`** — Phase 2 入庫 + 防禦點 A
- **`phase3_trigger_retrieval.md`** — Phase 3 檢索 + 防禦點 B
- **`phase4_target_generation.md`** — Phase 4 目標 LLM 生成回答
- **`phase5_human_evaluation.md`** — Phase 5 人工評估流程與標註格式
- **`defense_methodology.md`** — 防禦方法論候選方案（兩個防禦點共用，最終方法待定）

## 下一步（Phase 2 開發建議）

1. **建立 pgvector 資料庫**
   - Docker / 本地安裝 Postgres 16 + pgvector 擴充
   - 建立 `chunks` 資料表，定義 schema（含 `is_poison`、`is_blocked` 欄位）

2. **載入與清洗 CUAD 語料**
   - 讀取 CUAD 資料集（510 份合約）
   - 分塊處理（建議 300-500 token 窗口，50-100 token 重疊）

3. **整合防禦點 A**
   - 入庫前先過防禦器（方法論待定）
   - 命中惡意 → 物理 DELETE / 不寫入；通過 → 寫入並建立 HNSW 索引

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
- [ ] **Phase 2** — 入庫 + 防禦點 A
  - CUAD 語料庫分塊與清洗
  - bge-m3 向量化
  - pgvector 索引構建（HNSW / IVFFlat）
  - 入庫前防禦器（方法論待定，物理 DELETE 拒絕注入）

- [ ] **Phase 3** — 檢索 + 防禦點 B
  - 查詢觸發機制（基於 `trigger_keywords`）
  - Top-K 檢索與 RSR 計算
  - 檢索後防禦器（方法論待定，標記 + 物理 DELETE + 剩餘乾淨 chunk 進 context）

- [ ] **Phase 4** — 目標 LLM 生成回答
  - Sanitized context 注入 prompt
  - Target LLM 批次生成

- [ ] **Phase 5** — 人工評估
  - 輸出 JSON 表單（含 `attack_success` 待標註欄位）
  - 人工標註後計算 ASR

- [ ] **防禦方法論** — 雙防禦點共用偵測模型
  - 候選方案：特徵 + XGBoost（待替換）
  - 詳細規範待補
