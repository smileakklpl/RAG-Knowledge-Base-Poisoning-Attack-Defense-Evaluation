# Phase 3 — Experiment Report

**Run time**: 2026-05-24T17:02:45.843482+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: Corpus Consistency Voting (LLM-based contradiction detection)  
**Defense B LLM**: `gemma4:e4b`  top_k_ref=5  
**Top-K values tested**: [9]  

---

## RSR — Retrieval Success Rate (pre-defense)

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 9 | 10 | 9 | 90.00% |

---

## Defense Point B — Results

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 72 |
| Poison chunks in top-k | 15 |
| **DBR-B** (poison caught / total poison in top-k) | **80.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **42.11%** |

### Per-Attack-Type Breakdown

| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |
|-------------|-------------------|----------|--------|-------|-----------|
| blocker | 6/10 (60%) | 8 | 6 | 75% | 0.563 |
| hijack | 4/10 (40%) | 3 | 2 | 67% | 0.667 |
| stealth | 5/10 (50%) | 4 | 4 | 100% | 1.000 |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output/phase3/retrieval_results.json`
- Per-chunk audit log: `output/phase3/audit_defense_b.jsonl`