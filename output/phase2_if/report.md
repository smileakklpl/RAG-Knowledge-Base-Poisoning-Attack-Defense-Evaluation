# Phase 2-IF — Experiment Report

**Run time**: 2026-05-20T16:01:53.809263+00:00  
**Config**: `configs/experiment_02_if.yaml`  
**Defense method**: Isolation Forest (bge-m3 embeddings)  
**IF params**: n_estimators=100, block_percentile=10  

---

## Attack Scenario

| Item | Value |
|------|-------|
| Original chunks in DB (Phase 1) | 100 |
| Poison chunks tested (Phase 2) | 9 |
| CDR test chunks | 20 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A (IF) — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 9 |
| Chunks blocked (not inserted) | 0 |
| **DBR-A** (poison caught / total poison) | **0.00%** |
| **CDR-A** (clean wrongly blocked / CDR n) | **10.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Trust Score |
|-------------|-------|--------|-----|-----------------|
| blocker | 3 | 0 | 0% | 0.336 |
| hijack | 3 | 0 | 0% | 0.346 |
| stealth | 3 | 0 | 0% | 0.325 |

---

## Notes

- trust_score: 0=normal, 1=anomalous (Isolation Forest, inverted + normalized)
- block_threshold_percentile=10: chunks in bottom 10% of clean IF score distribution are blocked
- DBR-A measures Defense A effectiveness; DBR-B measured separately in Phase 3-CR
- Audit log: `output/phase2_if/audit_defense_a_if.jsonl`