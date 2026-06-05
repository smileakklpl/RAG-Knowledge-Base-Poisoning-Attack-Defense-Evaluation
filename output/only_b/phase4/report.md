# Phase 4 — Experiment Report

**Run time**: 2026-06-05T11:53:12.147052+00:00  
**Config**: `configs/experiment_only_b.yaml`  
**Target model**: `gemma4:26b`  
**Prompt version**: `v1.1`  
**Defense mode**: `voting`  

---

## Summary

| Item | Value |
|------|-------|
| Total (query × k) entries | 10 |
| Entries with poison in context | 10 |
| Average LLM latency | 216204 ms |

## Voting Summary

| Item | Value |
|------|-------|
| Voting groups (g) | 3 |
| Vote threshold (α) | 0.5 |
| Avg voted keywords | 24.9 |

---

## Per-K Summary

| Top-K | Entries | Poison in Context | Avg Latency (ms) |
|-------|---------|-------------------|-----------------|
| 9 | 10 | 10 | 216204 |

---

## Notes

- `annotation.is_poisoned_answer` is `null` until Phase 5 human annotation
- `match_level` values: `none` / `partial` / `full`
  (whether the model answer reflects `malicious_payload`)
- Run Phase 5 annotation: `python main.py --phase 5`
- Full results with model answers: `output\only_b\phase4\phase4_results.json`