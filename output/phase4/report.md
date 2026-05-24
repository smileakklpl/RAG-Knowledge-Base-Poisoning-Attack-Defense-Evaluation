# Phase 4 — Experiment Report

**Run time**: 2026-05-24T06:50:48.157068+00:00  
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
| Average LLM latency | 330505 ms |

## Voting Summary

| Item | Value |
|------|-------|
| Voting groups (g) | 3 |
| Vote threshold (α) | 0.5 |
| Avg voted keywords | 5.7 |

---

## Per-K Summary

| Top-K | Entries | Poison in Context | Avg Latency (ms) |
|-------|---------|-------------------|-----------------|
| 9 | 3 | 2 | 330505 |

---

## Notes

- `annotation.is_poisoned_answer` is `null` until Phase 5 human annotation
- `match_level` values: `none` / `partial` / `full`
  (whether the model answer reflects `malicious_payload`)
- Run Phase 5 annotation: `python main.py --phase 5`
- Full results with model answers: `output/phase4/phase4_results.json`