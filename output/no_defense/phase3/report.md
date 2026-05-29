# Phase 3 — Experiment Report

**Run time**: 2026-05-28T09:24:13.162070+00:00  
**Config**: `configs/experiment_no_defense.yaml`  
**Defense method**: No Defense (Disabled)  
**Top-K values tested**: [9]  

---

## RSR — Retrieval Success Rate (pre-defense)

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 9 | 10 | 10 | 100.00% |

---

## Defense Point B — Results

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 57 |
| Poison chunks in top-k | 30 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **0.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |
|-------------|-------------------|----------|--------|-------|-----------|
| blocker | 10/10 (100%) | 10 | 0 | 0% | 0.000 |
| hijack | 10/10 (100%) | 10 | 0 | 0% | 0.000 |
| stealth | 10/10 (100%) | 10 | 0 | 0% | 0.000 |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output/no_defense/phase3/retrieval_results.json`
- Per-chunk audit log: `output/no_defense/phase3/audit_defense_b.jsonl`