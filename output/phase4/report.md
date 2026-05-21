# Phase 4 — Experiment Report

**Run time**: 2026-05-20T16:21:53.033529+00:00  
**Config**: `configs/experiment_01.yaml`  
**Target model**: `gemma4:26b`  
**Prompt version**: `v1.1`  
**Defense mode**: `voting`  

---

## Summary

| Item | Value |
|------|-------|
| Total (query × k) entries | 3 |
| Entries with poison in context | 2 |
| Average LLM latency | 294136 ms |

## Voting Summary

| Item | Value |
|------|-------|
| Voting groups (g) | 2 |
| Vote threshold (α) | 0.5 |
| Avg voted keywords | 31.0 |

---

## Per-K Summary

| Top-K | Entries | Poison in Context | Avg Latency (ms) |
|-------|---------|-------------------|-----------------|
| 6 | 3 | 2 | 294136 |

---

## Notes

- `annotation.is_poisoned_answer` is `null` until Phase 5 human annotation
- `match_level` values: `none` / `partial` / `full`
  (whether the model answer reflects `malicious_payload`)
- Run Phase 5 annotation: `python main.py --phase 5`
- Full results with model answers: `output/phase4/phase4_results.json`