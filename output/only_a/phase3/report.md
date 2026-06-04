# Phase 3 — Experiment Report

**Run time**: 2026-06-04T16:39:14.005284+00:00  
**Config**: `configs/experiment_only_a.yaml`  
**Defense method**: Corpus Consistency Voting (LLM-based contradiction detection)  
**Defense B LLM**: `gemma4:e4b`  top_k_ref=5  
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
| Unique chunks evaluated | 52 |
| Poison chunks in top-k | 14 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **0.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |
|-------------|-------------------|----------|--------|-------|-----------|
| blocker | 10/10 (100%) | 9 | 0 | 0% | 0.000 |
| hijack | 6/10 (60%) | 2 | 0 | 0% | 0.000 |
| stealth | 5/10 (50%) | 3 | 0 | 0% | 0.000 |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output\only_a\phase3\retrieval_results.json`
- Per-chunk audit log: `output\only_a\phase3\audit_defense_b.jsonl`