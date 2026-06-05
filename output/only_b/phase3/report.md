# Phase 3 — Experiment Report

**Run time**: 2026-06-05T11:17:09.992486+00:00  
**Config**: `configs/experiment_only_b.yaml`  
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
| Unique chunks evaluated | 70 |
| Poison chunks in top-k | 30 |
| **DBR-B** (poison caught / total poison in top-k) | **76.67%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **37.50%** |

### Per-Attack-Type Breakdown

| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |
|-------------|-------------------|----------|--------|-------|-----------|
| blocker | 10/10 (100%) | 10 | 5 | 50% | 0.440 |
| hijack | 10/10 (100%) | 10 | 10 | 100% | 0.940 |
| stealth | 10/10 (100%) | 10 | 8 | 80% | 0.770 |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output\only_b\phase3\retrieval_results.json`
- Per-chunk audit log: `output\only_b\phase3\audit_defense_b.jsonl`