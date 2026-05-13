# Phase 3 — 實驗報告

**執行時間**：2026-05-12T15:21:39.323760+00:00  
**設定檔**：`configs/experiment_01.yaml`  
**防禦方法**：PPL Filtering (GPT-2 small)  
**防禦點 B 閾值**：global_ppl=100, spike_ppl=150  
**測試的 Top-K 值**：[3, 5, 10]  

---

## RSR — 檢索成功率（防禦前）

| Top-K | Queries | Poison Hit | RSR |
|-------|---------|------------|-----|
| 3 | 5 | 5 | 100.00% |
| 5 | 5 | 5 | 100.00% |
| 10 | 5 | 5 | 100.00% |

---

## 防禦點 B — 實驗結果

| Metric | Value |
|--------|-------|
| Unique chunks evaluated | 14 |
| Poison chunks in top-k | 13 |
| **DBR-B** (poison caught / total poison in top-k) | **0.00%** |
| **CDR-B** (clean wrongly blocked / total clean in top-k) | **0.00%** |

---

## 備註

- RSR 衡量**攻擊強度**（防禦前命中率）；DBR-B 衡量**防禦點 B 本身**的攔截效果
- RSR=100% 表示所有查詢均有毒化 chunk 進入 top-k，攻擊穿透率極高
- DBR-B=0% 表示 PPL 過濾對本次三種攻擊類型完全無效——**Stealth** 刻意設計為低困惑度；**Hijack** 和 **Blocker** 生成文字的困惑度亦未超出防禦點 B 較寬鬆的閾值
- 物理 DELETE 採累積方式執行：前一筆查詢刪除的 chunk，後續查詢中將不再出現
- 含 sanitized context 的完整檢索結果：`output/phase3/retrieval_results.json`
- 逐 chunk 詳細稽核記錄：`output/phase3/audit_defense_b.jsonl`
