# Phase 2 — Experiment Report

**Run time**: 2026-05-16T14:29:07.535391+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: PPL Filtering (GPT-2 small, global + sliding-window spike)  
**Defense A thresholds**: global_ppl=80.0, spike_ppl=120.0  

---

## Attack Scenario

攻擊者從資料庫撈出乾淨 chunks，修改後嘗試重新注入。

| Item | Value |
|------|-------|
| Original chunks in DB (Phase 1) | 100 |
| Poison chunks tested (Phase 2) | 5 |
| CDR test chunks | 20 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 4 |
| Chunks blocked (not inserted) | 1 |
| **DBR-A** (poison caught / total poison) | **20.00%** |
| **CDR-A** (clean wrongly blocked / CDR test n) | **5.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 1 | 0 | 0% | 0.421 |
| hijack | 1 | 0 | 0% | 0.327 |
| stealth | 3 | 1 | 33% | 0.713 |

---

## Notes

- `n_clean_chunks=100` — Phase 1 預載乾淨 chunks 數量
- `n_cdr_chunks=20` — CDR 測試用 CUAD chunks（seed+1，非 DB 原始集合）
- DBR-A 低代表攻擊者的 stealth 能力強（PPL 難以偵測）
- Audit log: `output/phase2/audit_defense_a.jsonl`