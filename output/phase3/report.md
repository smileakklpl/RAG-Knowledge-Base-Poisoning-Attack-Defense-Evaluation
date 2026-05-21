# Phase 3 — Experiment Report

**Run time**: 2026-05-20T15:15:27.671351+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: PPL Filtering (GPT-2 small)  
**Thresholds (Defense B)**: global_ppl=100, spike_ppl=150  
**Top-K values tested**: [6]  

---

## RSR — Retrieval Success Rate (pre-defense)

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 6 | 3 | 2 | 66.67% |

---

## Defense Point B — Results

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 15 |
| Poison chunks in top-k | 4 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **0.00%** |

---

## Notes

- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B
- Stealth attacks are expected to have low DBR-B (low PPL by design)
- Physical DELETE applied incrementally: earlier queries' deletions affect later queries
- Retrieval results with sanitized context: `output/retrieval_results.json`
- Per-chunk audit log: `output/audit_defense_b.jsonl`