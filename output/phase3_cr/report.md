# Phase 3-CR — Experiment Report

**Run time**: 2026-05-20T16:06:39.684930+00:00  
**Config**: `configs/experiment_02_if.yaml`  
**Defense method**: Counter-Retrieval Verification (NLI: deberta-v3-small)  
**Gray zone**: trust_score ∈ [0.1, 0.8)  
**NLI model**: cross-encoder/nli-deberta-v3-small  

---

## RSR — Retrieval Success Rate (pre-defense)

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 5 | 3 | 1 | 33.33% |

---

## Defense Point B (CR) — Results

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 14 |
| Poison chunks in top-k | 3 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **0.00%** |

### CR Action Breakdown

| Action | Count |
|--------|-------|
| counter_retrieval | 3 |
| skip_original | 12 |

---

## Notes

- `skip_original`: NULL trust_score → Phase 1 clean chunk, never evaluated
- `skip_normal`:   trust_score < gray_zone_lower → IF deemed very normal
- `auto_suspicious`: trust_score >= skip_cr_above → flagged without CR
- `counter_retrieval`: gray zone → claim extracted, NLI run on original chunks
- Evidence pool restricted to is_original=TRUE (prevents poison mutual validation)
- Physical DELETE applied per-query; earlier deletions affect later queries