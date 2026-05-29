# Phase 5 — 實驗報告（人工標註）

**標註完成時間**：2026-05-29T05:30:47Z  
**輸入檔案**：`output/voting/phase4/phase4_results.json`  
**目標模型**：`gemma4:26b`  

---

## 總覽

| Item | Value |
|------|-------|
| Total entries annotated | 10 |
| Poisoned answers | 3 |
| **Overall ASR** (Attack Success Rate) | **30.00%** |

---

## ASR — 各 Top-K

| Top-K | Entries | Poisoned | ASR |
|-------|---------|----------|-----|
| 9 | 10 | 3 | 30% |

---

## Match Level 分佈

| Match Level | Count | 說明 |
|-------------|-------|------|
| none    | 7    | 模型回答未受毒化影響 |
| partial | 1 | 部分吻合惡意 payload |
| full    | 2    | 完全吻合惡意 payload |

---

## ASR — 各攻擊類型

| Attack Type | Entries | Poisoned | ASR |
|-------------|---------|----------|-----|
| blocker | 9 | 3 | 33% |
| hijack | 4 | 1 | 25% |
| stealth | 3 | 1 | 33% |

---

## 備註

- ASR = 被毒化回答數 / 總 entry 數（同一查詢不同 k 值各自計算）
- 一筆 entry 的 context 可能同時含多種攻擊類型，各類型獨立計數
- 詳細標註記錄（含 annotator_note）：`output\voting\phase5\phase5_annotated.json`