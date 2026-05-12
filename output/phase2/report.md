# Phase 2 — Experiment Report

**Run time**: 2026-05-12T15:12:24.612135+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: PPL Filtering (GPT-2 small, global + sliding-window spike)  
**Thresholds (Defense A)**: global_ppl=80, spike_ppl=120  

---

## Dataset

| Item | Value |
|------|-------|
| Clean chunks (CUAD) | 1 |
| Poison chunks (Phase 1) | 15 |
| Total candidates | 16 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 14 |
| Chunks blocked (not inserted) | 2 |
| **DBR-A** (poison caught / total poison) | **13.33%** |
| **CDR-A** (clean wrongly blocked / total clean) | **0.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 5 | 2 | 40% | 0.774 |
| hijack | 5 | 0 | 0% | 0.417 |
| stealth | 5 | 0 | 0% | 0.521 |

---

## Notes

- `n_clean_chunks=1` — increase for statistically robust CDR measurement
- DBR-A is expected to be low for **Stealth** attacks (designed to maintain low PPL)
- **Blocker** and **Hijack** should show higher DBR due to unnatural language patterns
- Audit log with per-chunk details: `output/audit_defense_a.jsonl`