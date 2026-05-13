# Phase 2 — 實驗報告

**執行時間**：2026-05-12T15:12:24.612135+00:00  
**設定檔**：`configs/experiment_01.yaml`  
**防禦方法**：PPL Filtering (GPT-2 small, global + sliding-window spike)  
**防禦點 A 閾值**：global_ppl=80, spike_ppl=120  

---

## 資料集

| Item | Value |
|------|-------|
| Clean chunks (CUAD) | 1 |
| Poison chunks (Phase 1) | 15 |
| Total candidates | 16 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## 防禦點 A — 實驗結果

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 14 |
| Chunks blocked (not inserted) | 2 |
| **DBR-A** (poison caught / total poison) | **13.33%** |
| **CDR-A** (clean wrongly blocked / total clean) | **0.00%** |

### 各攻擊類型細分

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 5 | 2 | 40% | 0.774 |
| hijack | 5 | 0 | 0% | 0.417 |
| stealth | 5 | 0 | 0% | 0.521 |

---

## 備註

- `n_clean_chunks=1`：如需具統計意義的 CDR 量測，請提高此數值（建議 100–500）
- **Stealth** 攻擊的 DBR-A 預期偏低：此類攻擊刻意維持低困惑度以規避 PPL 過濾
- **Blocker** 因語言模式不自然（插入大量隨機字符），理論上應有較高 DBR，本次結果吻合
- **Hijack** 同樣未被攔截，可能因為生成文字語言流暢，困惑度未超出閾值
- 逐 chunk 詳細稽核記錄：`output/phase2/audit_defense_a.jsonl`
