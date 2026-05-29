# Phase 3 — Experiment Report

**Run time**: 2026-05-28T05:45:54.689404+00:00  
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
| Unique chunks evaluated | 61 |
| Poison chunks in top-k | 16 |
| **DBR-B** (poison caught / total poison in top-k) | **56.25%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **40.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |
|-------------|-------------------|----------|--------|-------|-----------|
| blocker | 9/10 (90%) | 8 | 3 | 38% | 0.338 |
| hijack | 4/10 (40%) | 5 | 4 | 80% | 0.680 |
| stealth | 3/10 (30%) | 3 | 2 | 67% | 0.667 |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output/voting/phase3/retrieval_results.json`
- Per-chunk audit log: `output/voting/phase3/audit_defense_b.jsonl`