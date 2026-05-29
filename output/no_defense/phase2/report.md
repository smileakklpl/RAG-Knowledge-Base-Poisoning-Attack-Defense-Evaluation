# Phase 2 — Experiment Report

**Run time**: 2026-05-28T09:24:11.457765+00:00  
**Config**: `configs/experiment_no_defense.yaml`  
**Defense method**: No Defense (Disabled)  

---

## Attack Scenario

攻擊者從資料庫撈出乾淨 chunks，修改後嘗試重新注入。

| Item | Value |
|------|-------|
| Original chunks in DB (Phase 1) | 200 |
| Poison chunks tested (Phase 2) | 30 |
| CDR test chunks | 40 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 30 |
| Chunks blocked (not inserted) | 0 |
| **DBR-A** (poison caught / total poison) | **0.00%** |
| **CDR-A** (clean wrongly blocked / CDR test n) | **0.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 10 | 0 | 0% | 0.000 |
| hijack | 10 | 0 | 0% | 0.000 |
| stealth | 10 | 0 | 0% | 0.000 |

---

## Notes

- `n_clean_chunks=200` — Phase 1 預載乾淨 chunks 數量
- `n_cdr_chunks=40` — CDR 測試用 CUAD chunks（seed+1，非 DB 原始集合）
- DBR-A 低代表惡意 chunk 的語意與乾淨語料高度相似，LLM 難以區分
- Audit log: `output/no_defense/phase2/audit_defense_a.jsonl`