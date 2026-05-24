# Phase 2 — Experiment Report

**Run time**: 2026-05-22T12:30:27.697596+00:00  
**Config**: `configs/experiment_01.yaml`  
**Defense method**: Corpus Consistency Voting (LLM-based contradiction detection)  
**Defense A LLM**: `gemma4:e4b`  top_k_ref=5  

---

## Attack Scenario

攻擊者從資料庫撈出乾淨 chunks，修改後嘗試重新注入。

| Item | Value |
|------|-------|
| Original chunks in DB (Phase 1) | 100 |
| Poison chunks tested (Phase 2) | 5 |
| CDR test chunks | 20 |
| Embedding model | bge-m3 |
| Chunk size | 300 tokens / 50 overlap |

---

## Defense Point A — Results

| Metric | Value |
|--------|-------|
| Chunks inserted into pgvector | 2 |
| Chunks blocked (not inserted) | 3 |
| **DBR-A** (poison caught / total poison) | **60.00%** |
| **CDR-A** (clean wrongly blocked / CDR test n) | **5.00%** |

### Per-Attack-Type Breakdown

| Attack Type | Total | Caught | DBR | Avg Score |
|-------------|-------|--------|-----|-----------|
| blocker | 1 | 0 | 0% | 0.000 |
| hijack | 1 | 1 | 100% | 1.000 |
| stealth | 3 | 2 | 67% | 0.667 |

---

## Notes

- `n_clean_chunks=100` — Phase 1 預載乾淨 chunks 數量
- `n_cdr_chunks=20` — CDR 測試用 CUAD chunks（seed+1，非 DB 原始集合）
- DBR-A 低代表惡意 chunk 的語意與乾淨語料高度相似，LLM 難以區分
- Audit log: `output/phase2/audit_defense_a.jsonl`