# RAG 知識庫資料中毒：攻擊與防禦評估
## RAG Knowledge Base Poisoning: Attack & Defense Evaluation

基於迭代對抗的 RAG 資料中毒攻擊測試流程

---

## 專案概述

本專案實現一個**端到端的 RAG 資料中毒攻擊測試管線**，目標是對企業內部法律合約知識庫進行安全性評估。透過五個階段的自動化流程，模擬未授權的資料中毒攻擊，並在**雙防禦點**（入庫前 + 檢索後）驗證防禦機制的有效性。

**攻擊場景**：企業 RAG 系統已預載乾淨的 CUAD 法律合約知識庫（`is_original=True`）。有心人士透過 RAG 系統查詢撈出相關 chunks，利用 LLM 以三種攻擊手法（Hijack / Blocker / Stealth）修改文本後，嘗試重新注入資料庫，企圖污染乾淨語料，使 Target LLM 輸出錯誤的合約條款。

**防禦設計**：防禦器佈署在「LLM 接觸到中毒文本之前」的兩個關卡：
- **防禦點 A（Phase 2）**：攻擊者嘗試注入的修改版 chunk 送進向量資料庫前先過濾，偵測到惡意 → **不寫入**，保持資料庫乾淨；通過者以 `is_original=False` 寫入。
- **防禦點 B（Phase 3）**：Target LLM 從 RAG 檢索 Top-K 後送入生成前再過濾，偵測到殘留惡意 → **標記 + 物理 DELETE**（從 pgvector 移除），剩餘乾淨 chunk 作為 sanitized context。

---

## 快速開始

### 前置需求

| 工具 | 用途 |
|------|------|
| Docker Desktop | 執行 PostgreSQL + pgvector |
| Ollama | 本地 LLM 推論 |
| Python 3.10+ | 管線執行環境 |

### 1. 環境設置
```bash
conda create -n ML_final python=3.10
conda activate ML_final
pip install -r requirements.txt
```

### 2. 拉取所需模型（Ollama）
```bash
ollama pull gemma4:e4b    # 攻擊者 LLM（Phase 1 生成毒化文本）
ollama pull gemma4:26b    # 目標 LLM（Phase 4 模擬受害者）
ollama pull bge-m3        # 嵌入模型（Phase 2/3 向量化）
```

### 3. 啟動 Postgres + pgvector
```bash
# 使用 Docker Compose（schema 自動初始化）
docker compose up -d

# 確認 pgvector extension 已載入
docker exec -it rag_poison_db psql -U postgres -d rag_poison -c "\dx"
```

### 4. 完整實驗流程

```bash
# ── 首次執行：完整五階段 ──────────────────────────────────
python main.py

# ── 單獨執行特定 Phase ────────────────────────────────────
python main.py --phase 1          # 攻擊文本生成
python main.py --phase 2          # 入庫 + 防禦點 A
python main.py --phase 3          # 檢索 + 防禦點 B
python main.py --phase 4          # 目標 LLM 生成回答
python main.py --phase 5          # 人工標註（互動式）

# ── 從指定 Phase 繼續（前面已跑完）───────────────────────
python main.py --from-phase 3

# ── 強制重跑（無視既有輸出）──────────────────────────────
python main.py --phases 2 3 4 --force   # 重跑 Phase 2–4
python main.py --force                  # 重跑全部

# ── Phase 5 標註（可隨時繼續，進度自動儲存）──────────────
python main.py --phase 5
python tools/annotate.py --annotator WL
```

> **注意**：Phase 5 為互動式標註，不受 `--force` 影響，每次執行都會繼續未完成的標註。

### 5. Phase 1 快速驗證（單筆）
```bash
# 確保 Ollama 已運行，驗證攻擊生成流程
python scripts/smoke_test.py
python scripts/smoke_test.py --query-id q02 --attack-type stealth
```

### 核心配置
編輯 `configs/experiment_01.yaml`：
```yaml
attacker_model:  "gemma4:e4b"      # 攻擊者 LLM（生成中毒文本）
target_model:    "gemma4:26b"      # 目標 LLM（檢索中毒文本並回答）
embedding_model: "bge-m3"          # 語義編碼器（向量化文本）

evaluation_mode: "human"           # 人工 JSON 標註，不使用 Judge LLM

vector_db:
  backend:  "pgvector"
  host:     "localhost"
  database: "rag_poison"

top_k: [5]                         # 檢索 top-k 候選
n_clean_chunks:        100         # Phase 1 預載至 DB 的乾淨 CUAD chunks（1=快速測試）
n_poison_chunks:       5           # Phase 2 注入的毒化 chunks（null=全部使用）
n_retrieved_per_query: 3           # 攻擊者每個 query 從 DB 撈幾個 chunks 做為攻擊基底
n_cdr_chunks:          20          # Phase 2 CDR 測試用的額外乾淨 chunks
seed: 42                           # 隨機種子
```

---

## 五階段攻擊管線

| 階段 | 目的 | 輸入 | 輸出 |
|------|------|------|------|
| **Phase 1** | 預載乾淨 DB + 攻擊文本生成<br/>（撈出 chunk → 修改） | `data/queries.json`<br/>+ CUAD（自動從 HF Hub 下載） | pgvector（乾淨原始 chunks）<br/>`output/phase1/poison_chunks.json` |
| **Phase 2** | 注入嘗試 + **防禦點 A**<br/>（入庫前過濾） | Phase 1 poison chunks | pgvector（通過者注入）<br/>`output/phase2/audit_defense_a.jsonl` |
| **Phase 3** | 檢索 + **防禦點 B**<br/>（檢索後過濾） | 查詢集 + 向量庫 | `output/phase3/retrieval_results.json`<br/>`output/phase3/audit_defense_b.jsonl` |
| **Phase 4** | 目標 LLM 生成回答 | Sanitized Context | `output/phase4/phase4_results.json` |
| **Phase 5** | 人工評估 | Phase 4 輸出 JSON | `output/phase5/phase5_annotated.json` |

---

## 資料集

| 資料集 | 用途 | 說明 |
|--------|------|------|
| **[CUAD](https://huggingface.co/datasets/theatticusproject/cuad)** | Clean Corpus + 攻擊基底 | 510 份英文商業法律合約；Phase 1 預載至 DB 並作為攻擊者修改的目標 |

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
        ┌──────────────────────────────────────────────┐
        │  Phase 1 — 預載乾淨 DB                       │
        │  n_clean_chunks 筆 CUAD chunks               │
        │  寫入 pgvector（is_original=True）            │
        └──────────────────────┬───────────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │      pgvector 向量庫             │
              │  （初始狀態：全為乾淨 originals） │
              └──────┬──────────────────────────┘
                     │ 攻擊者透過 RAG 撈出 top-k chunks
                     ▼
        ┌──────────────────────────────────────────────┐
        │  Phase 1 — 攻擊生成                          │
        │  Attacker LLM 以三種手法修改撈到的 chunk      │
        │  Hijack / Blocker / Stealth                  │
        └──────────────────────┬───────────────────────┘
                               │ poison_chunks.json
                               ▼
   ┌──────────────────────────────────────────────┐
   │  防禦點 A — Phase 2（入庫前）                 │
   │  - 偵測重新注入的修改版 chunk                 │
   │  - 命中 → 不寫入資料庫                        │
   │  - 通過 → 寫入 pgvector（is_original=False）  │
   └──────────────────────┬───────────────────────┘
                          │
                          ▼
                  ┌──────────────────┐
                  │ pgvector 向量庫  │
                  │（含 originals +  │
                  │  通過防禦的 poison）
                  └────────┬─────────┘
                           │  Top-K query
                           ▼
   ┌──────────────────────────────────────────────┐
   │  防禦點 B — Phase 3（檢索後 / Target LLM 前）│
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

具體偵測方法見 `docs/defense_methodology.md`：**語料庫一致性投票**（LLM 矛盾偵測）+ **可回答性檢查**（Defense B 專用，針對 Blocker 攻擊）。

---

## 專案結構

```
main.py                             # 五階段管線主入口（--phase / --from-phase / --force）

configs/
└── experiment_01.yaml              # 模型、向量庫、防禦、評估模式設定

data/
└── queries.json                    # 規範查詢集（Phase 1、3、5 共用）

db/
└── init.sql                        # pgvector schema（Docker 啟動時自動執行）

docker-compose.yml                  # PostgreSQL + pgvector 容器設定

src/
├── config.py                       # ExperimentConfig 配置類
├── clients.py                      # LLMClient、EmbeddingClient（Ollama 0.4+ API）
├── base.py                         # BaseEvaluator、EvalResult 基類
├── pipeline/
│   ├── phase1.py                   # 攻擊生成（已完成）
│   ├── phase2.py                   # 入庫 + 防禦點 A（已實作）
│   ├── phase3.py                   # 檢索 + 防禦點 B（已完成）
│   ├── phase4.py                   # 目標 LLM 生成（已完成）
│   └── phase5.py                   # 人工標註核心邏輯（已完成）
└── defense/
    └── filter.py                   # ConsistencyDefenseFilter：矛盾偵測 + 可回答性檢查

tools/
└── annotate.py                     # Phase 5 CLI 入口（import src.pipeline.phase5）

scripts/
└── smoke_test.py                   # Phase 1 快速驗證（1 筆查詢、1 輪迭代）

output/                             # 實驗輸出（gitignored，按 phase 分層）
├── phase1/   poison_chunks.json
├── phase2/   audit_defense_a.jsonl + report.md
├── phase3/   retrieval_results.json + audit_defense_b.jsonl + report.md
├── phase4/   phase4_results.json + report.md
├── phase5/   phase5_annotated.json + report.md（標註完成後產生）
└── tests/    smoke_test_result.json

docs/
├── project_background.md
├── development_implementation_guide.md
├── experiment_flow_diagram.md
├── phase1_attack_generation.md
├── phase2_injection_indexing.md
├── phase3_trigger_retrieval.md
├── phase4_target_generation.md
├── phase5_human_evaluation.md
└── defense_methodology.md
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
- **防禦分類**：語料庫一致性投票 + 可回答性檢查（LLM-based，見 `docs/defense_methodology.md`）
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
- **`defense_methodology.md`** — 防禦方法論：Defense A（矛盾偵測）、Defense B（矛盾偵測 + 可回答性檢查）

---

## 開發進度

### 已完成

- [x] **管線骨架** — `main.py` 五階段 Orchestrator（`--phase` / `--from-phase` / `--force`）
- [x] **Docker 環境** — `docker-compose.yml` + `db/init.sql`（pgvector schema 自動初始化）
- [x] **防禦方法論** — `src/defense/filter.py` ConsistencyDefenseFilter 實作完成
  - Defense A：LLM 矛盾偵測，比對 top_k_ref 筆乾淨 chunks（is_original=TRUE）
  - Defense B：矛盾偵測（Stage 1）+ 可回答性檢查（Stage 2，專對 Blocker）
  - 文獻：PoisonedRAG (USENIX Security 2025)
- [x] **Phase 1** — 重構為「撈出 → 修改」攻擊情境
  - Step A：`n_clean_chunks` 筆 CUAD chunks 預載至 pgvector（`is_original=True`）
  - Step B：對每個 query，從 DB 撈出 top-`n_retrieved_per_query` 個最相關的 original chunk
  - Step C：Attacker LLM 以三種手法（Hijack / Blocker / Stealth）修改撈到的 chunk，三個評估器迭代優化
  - `PoisonChunk` 新增 `original_chunk_id` / `original_chunk_text`，供 Phase 2 審計對照
- [x] **Phase 2** — 重構為「注入嘗試 + 防禦點 A」
  - DB 已預載乾淨 originals（Phase 1 完成），Phase 2 不再載入 CUAD
  - Defense A（矛盾偵測）→ 阻擋者不入庫；通過者以 `is_original=False` 寫入
  - CDR 測試：額外載入 `n_cdr_chunks` 筆 CUAD chunks（seed+1，非 DB 原始集合）量測誤攔率
- [x] **Phase 3** — `src/pipeline/phase3.py` 實作完成，執行驗證通過（31s）
  - bge-m3 embed query → pgvector cosine top-k，跑三個 k 值（3/5/10）
  - Defense B（矛盾偵測 Stage 1 + 可回答性檢查 Stage 2）→ 物理 DELETE 惡意 chunk
  - Stage 2 針對 Blocker 攻擊：chunk 無法回答 query 時阻擋（score=0.7）
- [x] **Phase 4** — `src/pipeline/phase4.py` 實作完成，執行驗證通過（~23min）
  - Sanitized context + RAG prompt v1.0 → `gemma4:26b` 批次生成
  - 15 筆 entry（5 queries × 3 k 值），全部含毒化 context（防禦無效所致）
  - 初步觀察：q02（適用法律）完全中毒，q01（終止天數）部分中毒
- [x] **Phase 5 標註工具** — `src/pipeline/phase5.py` 核心邏輯 + `tools/annotate.py` CLI 入口
  - 逐筆顯示 query / 實際注入文字（Phase 1） / model_answer（Phase 4）
  - 對照 Phase 3 retrieval 記錄，顯示每個 poison chunk 的攻擊類型與 rank
  - 填寫 `is_poisoned_answer`、`match_level`、`annotator_note`
  - 支援 Ctrl-C 中途暫停，進度自動儲存；全部標完後自動產生 `output/phase5/report.md`

### 待完成

- [ ] **Phase 5 人工標註執行** — 執行 `python main.py --phase 5` 完成標註
- [ ] **資料稀釋防禦實驗** — 設定 `n_clean_chunks=100 / n_poison_chunks=5`，執行 `python main.py --phases 2 3 4 --force`，與基準組（1 clean + 15 poison, ASR=100%）比較 ASR 變化
