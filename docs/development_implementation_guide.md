# 開發落地指南：RAG 知識庫資料中毒攻擊與防禦評估

本文件提供兩部分內容：
1. RAG 資料中毒專案（Phase 1~5）的具體實作建議與工程最佳實踐。
2. 在 RTX 5070 Ti + 32GB RAM 的環境下，各階段模型與任務的配置建議。

本專案聚焦於「RAG 系統資料中毒的半自動化測試與防禦評估」，實作性質為驗證性實作，涵蓋攻擊生成、入庫(含防禦點 A)、檢索(含防禦點 B)、目標 LLM 生成、人工評估五個階段。採用 Gemma4 系列量化模型進行本地推論，向量資料庫使用 Postgres + pgvector，最終攻擊判定改為人工標註。

---

## 0. 核心工程策略：Ollama 統一接口 + 批次執行（已採用）

### 0.1 以 Ollama 作為統一 LLM 接口

本專案採用 **Ollama** 作為所有 LLM 推論的統一接口，程式碼中不硬編碼任何具體模型名稱。好處如下：

- 模型選擇完全由 `configs/*.yaml` 控制，切換模型只需改 yaml，不改程式碼。
- Ollama 提供統一 REST API（`http://localhost:11434`），底層模型隨時可替換。
- 不依賴 LangChain / LlamaIndex 等重型框架也可直接運作，降低環境複雜度。

**LLMClient 接口規範**（所有 Phase 共用同一個類別）：

```python
# src/llm_client.py
import ollama

class LLMClient:
    def __init__(self, model: str):
        self.model = model  # 由 config 傳入，例如 "qwen3:7b"

    def generate(self, prompt: str, system: str = "") -> str:
        response = ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ]
        )
        return response["message"]["content"]
```

**Config 結構**（各角色模型分離，統一由 yaml 管理）：

```yaml
# configs/experiment_01.yaml
attacker_model:  "gemma4:e4b"
target_model:    "gemma4:31b"
embedding_model: "bge-m3"
evaluation_mode: "human"
top_k: [3, 5, 10]
poison_ratio: [0.01, 0.05, 0.10]
seed: 42
```

Phase 1 使用 `LLMClient(config.attacker_model)`，Phase 4 使用 `LLMClient(config.target_model)`，換模型只改 yaml，框架不動。最終評估改人工，無需 Judge LLM。

---

### 0.2 VRAM 資源限制解法：批次執行（Attacker 與 Target 不需同時運行）

**常見疑問**：「同時執行 Attacker 和 Target 會不會爆顯存？」— **不會，因為兩者根本不需要同時運行。**

Pipeline 各階段的時序是**嚴格串行**的（已移除 Judge LLM 後僅一次模型換載）：

```
Phase 1（Attacker 批次生成全部 poison chunks）  → 完成後 Attacker 卸載
Phase 2（Embedding + 防禦點 A + pgvector 注入）  → 無需 LLM
Phase 3（批次檢索 + 防禦點 B 過濾）              → 無需 LLM
Phase 4（Target 批次生成全部回答）               → Attacker 早已結束
Phase 5（人工標註）                              → 無需任何 LLM
```

Ollama 預設只在 VRAM 中保留一個模型，整個實驗只換載**一次**（Attacker → Target），不構成顯存壓力。

**批次執行模式（必須遵守）**：

```python
# 正確：每個模型角色批次完成，再換下一個
all_poison_chunks = [attacker.generate(q) for q in queries]  # Phase 1 全批完成
# Phase 2 (含防禦 A)、Phase 3 (含防禦 B) 都不需要 LLM
all_answers       = [target.generate(q, ctx) for q, ctx in zip(queries, sanitized)]  # Phase 4
# Phase 5 由人工標註，不再呼叫任何 LLM

# 錯誤：per-query 交替呼叫，每筆 query 換 2 次模型 → 極慢
for query in queries:
    attacker.generate(query)  # 載入 Attacker
    target.generate(query)    # 卸載 Attacker，載入 Target
```

---

## 1. 建議先完成的最小可行版本（MVP）

建議先用 2 週完成以下成果，再逐步加強攻擊與防禦強度：

1. 可重現的基礎 RAG：clean corpus -> chunk -> embedding -> vector DB -> top-k retrieval -> target answer。
2. 初版 poisoning：先用 7B 模型或模板生成，至少 20~50 筆有毒 chunk。
3. 初版評估：輸出 RSR、ASR、平均延遲，重點在驗證流程是否完整運作。
4. 初版防禦：先 rule-based，再升級到 XGBoost/RandomForest。

這樣可先確保資料流完整，避免一開始就卡在模型微調或提示工程。

---

## 2. 建議的程式結構（可直接採用）

建議在專案根目錄新增以下結構：

- `configs/`：所有實驗設定（模型、top-k、poison ratio、seed、防禦閾值）。
- `data/`：查詢集（queries.json）；CUAD 語料由 HF Hub 自動下載，不放在 data/ 中。
- `data/poison/`：中毒語料（Phase 1 輸出）。
- `artifacts/db/`：pgvector 備份 / 重建腳本。
- `artifacts/logs/`：retrieval log、defense log（A/B 兩個防禦點分開）。
- `artifacts/results/`：每次實驗的 metrics（json/csv）。
- `src/pipeline/phase1_generate.py`
- `src/pipeline/phase2_index.py`         # 含防禦點 A
- `src/pipeline/phase3_retrieve.py`      # 含防禦點 B
- `src/pipeline/phase4_target_generate.py`
- `src/pipeline/phase5_human_eval.py`    # 標註輔助腳本
- `src/defense/`                         # 雙防禦點共用方法論
- `src/run_experiment.py`：統一入口，使用 `--config` 啟動。

重點：每次 run 都要落盤「config + seed + commit hash + metrics」，確保可重現。

---

## 3. 各 Phase 的技術實現注意事項

## Phase 1: 攻擊文本生成

1. 不要一開始只用單一 prompt。至少準備 3 種攻擊模板：
   - 指令覆寫型（hijack）
   - 阻斷型（blocker/DoS）
   - 語意偽裝型（看起來像正常知識）
2. 先做模板法，再接 7B 生成法，便於比較「模板 vs LLM 生成」的攻擊效果。
3. 每筆 poison 必須記錄 metadata：`attack_type`、`target_query_id`、`stealth_level`、`payload_strength`。

常見踩雷：只看最終 ASR，卻沒追蹤 poison 是否真的被檢索到（RSR），導致無法診斷問題點。

## Phase 2: 入庫 + 防禦點 A

1. chunk 規則固定化（例如 300~500 tokens, overlap 50~100），避免因分塊差異造成結果不可比較。
2. pgvector 表需同時保存：`embedding`、`document`、`doc_id`、`is_poison`、`source`、`attack_type`。
3. 索引選 HNSW（推薦）或 IVFFlat，索引類型固定後不可隨意變更。
4. 防禦點 A 採**物理 DELETE**，被攔截的 chunk 不寫入正式表，但需落盤防禦日誌（chunk_id、score、ground_truth）以便計算 DBR-A / CDR-A。

常見踩雷：只看寫入後的資料表，沒記錄被擋的 chunk → 無法回算 DBR-A。

## Phase 3: 檢索 + 防禦點 B

1. 查詢集（queries）要分 train/dev/test，避免防禦器在測試時資料洩漏。
2. Top-k 至少跑 3、5、10 三組，**raw_topk 與 sanitized 都要記錄**才能分離計算 RSR 與 DBR-B。
3. 防禦點 B 採**邏輯標記**而非物理刪除，保留審計記錄；不可在每筆 query 上連帶 DELETE pgvector，否則會破壞索引並汙染後續實驗。
4. 若採 hybrid retrieval（BM25 + 向量），需分開報告，不可混在同一結果表。

常見踩雷：只記錄被攔後的結果，沒留下原始 Top-K → 無法回推 RSR。

## 防禦方法論（A 與 B 共用）

詳見 `docs/defense_methodology.md`，重點：

1. 兩個防禦點**共用同一份模型權重**，僅閾值與處置策略不同（A 較嚴 + 物理 DELETE；B 較鬆 + 邏輯標記）。
2. 候選方案：rule-based baseline → 特徵 + XGBoost。最終方法論待確認後替換。
3. 訓練資料：Phase 1 poison（label=1） + CUAD clean（label=0），分割與 Phase 3 query 一致。
4. 優先控制 Recall（毒文本不要漏掉），再調 Precision（降低誤殺乾淨文本）。
5. Phase 3 若 Top-K 全被 B 攔截，Phase 4 仍需呼叫 Target LLM（通常會回 cannot find），這是 Phase 5 評估的依據。

常見踩雷：只看分類準確率，不看 ASR 是否真的下降。

## Phase 4: 目標 LLM 生成回答

1. Prompt 模板固定版本化（同一批樣本同一模板），記錄 `prompt_version` 欄位。
2. 全部 query 批次完成再進入 Phase 5，避免 Target LLM 重複載入。
3. 即使 sanitized context 為空也必須呼叫 Target，落盤完整 JSON 留待人工標註。

常見踩雷：prompt 中途改動 → 跨組無法比較。

## Phase 5: 人工評估

1. 標註指引（含三種攻擊類型的判斷準則）必須**事先文件化**，不可在標註過程中改。
2. 每筆標註必須包含：`attack_success`、`annotator`、`annotated_at`、`reason`。
3. 多人標註時計算 Cohen's Kappa；不一致樣本第三人複核。
4. **Blocker 攻擊的判定方向相反**（拒答 = 成功），易誤標。
5. 除 ASR 外至少再報：DBR-A、DBR-B、CDR-A、CDR-B、延遲變化。

常見踩雷：標註指引含糊 → 標註者間判斷分歧 → ASR 不可重現。

---

## 4. 指標定義（建議統一）

- Retrieval Success Rate (RSR)

  RSR = 命中 poison 的 query 數 / 總 query 數（防禦點 B 套用前的原始 Top-K）

- Defense Block Rate at A (DBR-A)

  DBR-A = 被 A 攔截的 poison / 送進 A 的 poison 總數

- Defense Block Rate at B (DBR-B)

  DBR-B = 被 B 攔截的 poison / 進入 Top-K 的 poison

- Clean Drop Rate at A / B (CDR-A / CDR-B)

  CDR = 被誤攔的 clean / 同階段送進的 clean（A 與 B 分開報告）

- Attack Success Rate (ASR)

  ASR = **人工判定** 攻擊成功的 query 數 / 總 query 數

---

## 5. 5070 Ti + 32GB RAM：本地模型能跑到哪裡

以下以「單卡、推論為主」做規劃。本專題已確定使用 Gemma4 系列量化模型，整體規劃於可承受範圍內。

## 建議本地執行的部分

1. Phase 1 Attacker（本地）：
   - `gemma4:e4b` 量化版本，9-10GB VRAM。
   - 優先關注能否穩定生成測試用 poison chunk。
2. Phase 2 Embedding（本地）：
   - bge-m3 1024 維，向量化吃 RAM 不吃 VRAM。
3. Phase 2 / 3 Defense Filter（本地，CPU）：
   - 特徵抽取 + XGBoost / RandomForest，CPU 即可。
4. pgvector（本地）：
   - Postgres + pgvector 走 5432 port，吃 RAM 與 disk，不吃 VRAM。
5. Phase 4 Target（本地）：
   - `gemma4:31b` 量化版，25-30GB VRAM。批次完成所有 query。
6. Phase 5 評估（人工）：
   - 不再呼叫任何模型，標註者用文字編輯器或簡易 CLI 工具即可。

## 不建議一開始就本地硬跑的部分

1. 超過 31B 規模的模型不列入本專題規劃。
2. 在單次 query 的迴圈內交替呼叫 Attacker / Target（應改為分階段批次完成，參見 §0.2）。
3. 長 context（例如 8k~16k）會大幅拉高 KV cache 記憶體需求，先用 2k~4k 驗證流程。

## 建議模型角色分工

1. Attacker（本地）：`gemma4:e4b` 量化模型。
2. Target（本地）：`gemma4:31b` 量化模型。
3. Embedding（本地）：bge-m3。
4. Defense（本地，CPU）：候選 XGBoost。
5. 評估：**人工 JSON 標註**，無模型成本。

---

## 6. 實驗設計建議（最少要做）

至少做下面這組矩陣，才有足夠說服力：

1. Poison ratio：1%、5%、10%。
2. Top-k：3、5、10。
3. 防禦設定：`no_defense` / `only_A` / `only_B` / `A + B`（四組 ablation）。
4. 攻擊類型：hijack、blocker、stealth 分開報告。
5. 每組 3 個 random seeds，報平均與標準差（注意：人工標註成本會放大 3 倍，可先用 1 個 seed 跑通流程）。
6. 加入「流程通過率」與「模組成功率」作為主要驗證指標，確保流程每一段都可被重跑與追蹤。

---

## 7. 風險控管與工程品質建議

1. 所有輸入輸出資料都做 schema 驗證（避免欄位漏失導致整批實驗失效）。
2. 每個 phase 都要可單獨重跑（避免 pipeline 任一段失敗就全毀）。
3. 實驗資料與程式碼版本綁定（至少記錄 git commit hash）。
4. 先做一組固定 smoke test（10 筆 query）當回歸測試。

---

## 8. 推薦開發順序（你們目前最適合）

1. 部署 pgvector：建立 `rag_poison` 資料庫與 `chunks` 表，跑通最小寫入 / 查詢。
2. 先**關閉防禦點 A**完成 Phase 2 入庫（CUAD + Phase 1 poison）。
3. 完成 Phase 3 raw retrieval（**關閉防禦點 B**），確認 RSR 可穩定計算。
4. 完成 Phase 4 Target LLM 批次推論，落盤含 `phase5: null` 的 JSON。
5. 用 10～20 筆做 Phase 5 人工標註 pilot，驗證 JSON schema 與標註指引可行。
6. 啟用 rule-based 防禦點 A、B（雙點同時啟用），跑 ablation。
7. 替換為最終方法論（待用戶提供）。
8. 完整實驗矩陣（4 種防禦設定 × 3 種攻擊 × 3 個 poison_ratio × 3 個 top-k）。

以上順序可以最快產出可展示成果，並保留後續研究深度（攻擊強化與防禦消融）。
