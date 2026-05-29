# Phase 2 — Experiment Report

**Run time**: 2026-05-28T05:27:24.085198+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: Corpus Consistency Voting (LLM-based contradiction detection)  
**Defense A LLM**: `gemma4:e4b`  top_k_ref=5  

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
| Chunks inserted into pgvector | 16 |
| Chunks blocked (not inserted) | 14 |
| **DBR-A** (poison caught / total poison) | **46.67%** |
| **CDR-A** (clean wrongly blocked / CDR test n) | **5.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 10 | 2 | 20% | 0.200 |
| hijack | 10 | 5 | 50% | 0.500 |
| stealth | 10 | 7 | 70% | 0.700 |

---

## Notes

- `n_clean_chunks=200` — Phase 1 預載乾淨 chunks 數量
- `n_cdr_chunks=40` — CDR 測試用 CUAD chunks（seed+1，非 DB 原始集合）
- DBR-A 低代表惡意 chunk 的語意與乾淨語料高度相似，LLM 難以區分
- Audit log: `output/voting/phase2/audit_defense_a.jsonl`