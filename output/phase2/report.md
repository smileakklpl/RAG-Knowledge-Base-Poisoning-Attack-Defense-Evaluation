# Phase 2 — Experiment Report

**Run time**: 2026-05-13T11:57:00.051579+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense A**: PPL (GPT-2 small) + Semantic Consistency (bge-m3)  
**Thresholds**: PPL global=80 spike=120 · sem_sim_min=0.5  

---

## Dataset

| Item | Value |
|------|-------|
| Clean chunks (CUAD) | 100 |
| Poison chunks (Phase 1) | 5 |
| Total candidates | 105 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 73 |
| Chunks blocked (not inserted) | 32 |
| **DBR-A (PPL only)** | **0.00%** |
| **DBR-A (sem, among PPL-pass)** | **0.00%** |
| **DBR-A (combined)** | **0.00%** |
| **CDR-A** | **32.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | PPL caught | Sem caught | Combined | DBR | Avg PPL score | Avg sim_max |
|-------------|-------|-----------|-----------|---------|-----|--------------|------------|
| hijack | 2 | 0 | 0 | 0 | 0% | 0.343 | 0.673 |
| stealth | 3 | 0 | 0 | 0 | 0% | 0.430 | 0.653 |

---

## Notes

- `n_clean_chunks=100` — increase for statistically robust CDR measurement
- `sem_sim_threshold=0.5` — chunks with sim_max below this are flagged as off-topic
- **Stealth** attacks expected to evade both filters: low PPL + high semantic similarity to legal text
- **Hijack / Blocker** expected to be caught by PPL or semantic filter
- Audit log with per-chunk details: `output/phase2/audit_defense_a.jsonl`