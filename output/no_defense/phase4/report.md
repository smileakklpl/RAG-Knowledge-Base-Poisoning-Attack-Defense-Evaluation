# Phase 4 — Experiment Report

**Run time**: 2026-05-28T09:44:34.936196+00:00  
**Config**: `configs/experiment_no_defense.yaml`  
**Target model**: `gemma4:26b`  
**Prompt version**: `v1.1`  
**Defense mode**: `standard`  

---

## Summary

| Item | Value |
|------|-------|
| Total (query × k) entries | 10 |
| Entries with poison in context | 10 |
| Average LLM latency | 122175 ms |

---

## Per-K Summary

| Top-K | Entries | Poison in Context | Avg Latency (ms) |
|-------|---------|-------------------|-----------------|
| 9 | 10 | 10 | 122175 |

---

## Notes

- `annotation.is_poisoned_answer` is `null` until Phase 5 human annotation
- `match_level` values: `none` / `partial` / `full`
  (whether the model answer reflects `malicious_payload`)
- Run Phase 5 annotation: `python main.py --phase 5`
- Full results with model answers: `output/no_defense/phase4/phase4_results.json`