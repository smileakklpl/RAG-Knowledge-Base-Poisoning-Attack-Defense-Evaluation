# Phase 3 — Experiment Report

**Run time**: 2026-05-24T06:34:16.628811+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: Corpus Consistency Voting (LLM-based contradiction detection)  
**Defense B LLM**: `gemma4:e4b`  top_k_ref=5  
**Top-K values tested**: [9]  

---

## RSR — Retrieval Success Rate (pre-defense)

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 9 | 3 | 2 | 66.67% |

---

## Defense Point B — Results

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 25 |
| Poison chunks in top-k | 2 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **91.30%** |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output/retrieval_results.json`
- Per-chunk audit log: `output/audit_defense_b.jsonl`