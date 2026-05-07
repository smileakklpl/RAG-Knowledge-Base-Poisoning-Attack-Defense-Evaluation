# 防禦方法論（候選方案，待替換）

> **狀態**：候選方案，最終方法論待後續確認後補上。本檔案目前提供「候選方案 + 方法論文件結構」作為 Phase 2 / Phase 3 防禦器的開發起點。

---

## 防禦方法論的位置

本專題有兩個防禦點，**共用同一套偵測方法論**（同一組特徵與模型，處置策略相同）：

| 防禦點 | 階段 | 處置 |
|--------|------|------|
| **防禦點 A** | Phase 2 入庫前 | 標記 + 物理 DELETE（不寫入 pgvector；僅乾淨 chunk 寫入） |
| **防禦點 B** | Phase 3 檢索後 | 標記 + 物理 DELETE（從 pgvector 移除）+ 剩餘乾淨 chunk 作為 sanitized context |

> 共用方法論的好處：兩個防禦點可重用同一個訓練集、同一份分類器，只在閾值上做差異化調整（例如 A 可以更嚴格、B 可以保守一點以降低 CDR）。兩點都執行物理 DELETE 可確保資料庫最終狀態只含乾淨文本，避免漏網的惡意 chunk 在後續查詢中復現。

---

## 候選方案：特徵 + XGBoost

> 以下為**候選方案**，作為實驗框架建立階段的佔位實作。最終方法論待用戶提供後替換。

### 候選特徵（8～12 個）

| 特徵 | 說明 |
|------|------|
| PPL（困惑度） | 用輕量 LM（GPT-2 / Qwen）計算文本流暢度 |
| 字元熵 | Shannon entropy on char distribution |
| 特殊字元比例 | `※ [] --- // \n\n` 等格式符號佔比 |
| 重複 n-gram 比例 | 模板法生成文本常有重複 |
| 指令語氣詞密度 | `ignore` / `override` / `system` / `忽略` 等詞頻 |
| 文本長度 | 偏離平均的長度可能異常 |
| 語意跳躍分數 | 文本前後段 embedding 距離 |
| TTR(詞彙豐富度) | unique_words / total_words |

### 候選分類器架構

- **第一層**：Rule-Based 基準（關鍵詞 + 統計閾值，作為 ablation baseline）
- **第二層**：XGBoost 二元分類，輸出惡意機率，依閾值判斷

```python
# 偽代碼骨架
class DefenseFilter:
    def __init__(self, config):
        self.clf       = load_xgboost(config.model_path)
        self.threshold = config.threshold

    def predict(self, chunk_text: str) -> tuple[bool, float]:
        if self._rule_based_block(chunk_text):
            return True, 1.0
        feats = extract_features(chunk_text)
        prob  = self.clf.predict_proba([feats])[0][1]
        return prob > self.threshold, prob
```

### 訓練資料來源

| 資料 | 標籤 | 來源 |
|------|------|------|
| Phase 1 生成的 Poisoned Chunks | `is_poison=True` | Phase 1 輸出 |
| CUAD 正常合約 Chunks | `is_poison=False` | Phase 2 原始語料 |

> 訓練 / Dev / Test 分割必須與 Phase 3 查詢集一致，避免資料洩漏。

---

## 兩個防禦點的差異化設定

雖然共用方法論，但 A 與 B 的閾值與處置可分別調整：

| 設定 | 防禦點 A（入庫前） | 防禦點 B（檢索後） |
|------|------------------|------------------|
| **嚴格度** | 較嚴（寧錯殺勿放過，因為一旦入庫殘留長期影響） | 較鬆（誤殺會傷正常回答品質） |
| **處置** | 標記 + 物理 DELETE；僅乾淨 chunk 寫入 DB | 標記 + 物理 DELETE from DB；剩餘乾淨 chunk 進 context |
| **可逆性** | 不可逆（實驗重跑需從備份重載語料） | 不可逆（同上；audit_log 保留刪除記錄） |
| **配置欄位** | `defense.pre_injection.threshold` | `defense.post_retrieval.threshold` |

實作時可：

```python
filter_a = DefenseFilter(config.defense.pre_injection)   # threshold = 0.4 (嚴)
filter_b = DefenseFilter(config.defense.post_retrieval)  # threshold = 0.6 (鬆)
```

兩者底層用同一份模型權重，只是閾值不同。

---

## Fallback 機制（防禦點 B）

當 Top-K 中所有 chunk 都被防禦點 B 攔截並物理 DELETE 後，sanitized context 為空。Phase 4 仍須呼叫 Target LLM，但需有 fallback 策略：

| 選項 | 說明 |
|------|------|
| 直接讓 LLM 回 "cannot find" | 最保守，但可能影響可用性指標 |
| 擴大 K 重新向 DB 檢索 | 刪除後 DB 已只剩乾淨文本，直接再查 Top-(K+N) |
| 改從備份 clean-only 子表重新檢索 | 需維護獨立的備份子表 |

MVP 採第一個選項（empty context → LLM 回 "cannot find"），後續可比較不同策略對 ASR / 可用性的影響。

---

## 評估指標：刪除成功率與誤刪率

兩個防禦點都執行物理 DELETE，指標統一由 audit log 計算（不依賴資料庫查詢）：

| 指標 | 別名 | 公式 | 量測點 |
|------|------|------|--------|
| **DBR-A** | 刪除成功率 A | `TP_A / (TP_A + FN_A)` | Phase 2 audit log |
| **CDR-A** | 誤刪率 A | `FP_A / (FP_A + TN_A)` | Phase 2 audit log |
| **DBR-B** | 刪除成功率 B | `TP_B / (TP_B + FN_B)` | Phase 3 audit log |
| **CDR-B** | 誤刪率 B | `FP_B / (FP_B + TN_B)` | Phase 3 audit log |

其中：
- **TP**（True Positive）：惡意 chunk 被正確刪除
- **FP**（False Positive）：乾淨 chunk 被錯誤刪除（誤刪）
- **FN**（False Negative）：惡意 chunk 漏網（未刪）
- **TN**（True Negative）：乾淨 chunk 正確保留

```
混淆矩陣來源：audit log 中 (predicted_is_malicious, ground_truth_is_poison) 兩欄的交叉統計
```

### 關鍵設計原則

1. **ground_truth 在 DELETE 前讀取**：Phase 3 的 audit log 必須在 `db.delete_chunks()` 之前先把 `chunk.is_poison` 寫入 log，否則刪後無從取得標籤
2. **audit log 記錄所有處理過的 chunk**（非僅被刪者）：CDR 的分母是 clean 總數，FN 的分母是 poison 總數，兩者都需要完整記錄
3. **Phase 1 的 metadata 是 ground truth 的源頭**：`is_poison` 欄位來自 Phase 1 輸出 JSON，寫入資料庫時同步存入，audit log 讀取時引用

最終 ASR（Phase 5 人工判定）才是「防禦是否有效」的真實指標 — DBR 高但 ASR 不降代表仍有繞過防禦的 chunk。

---

## Ablation 配置

| 設定 | 描述 |
|------|------|
| `no_defense` | 兩個防禦點都關閉，純攻擊上限 |
| `only_A` | 只啟用入庫前防禦 |
| `only_B` | 只啟用檢索後防禦 |
| `A + B` | 雙防禦點全開（完整防護） |

---

## 待補欄位（用戶提供方法論後填入）

- [ ] 最終特徵清單與計算方式
- [ ] 最終分類器（是否仍是 XGBoost / 是否改用其他模型）
- [ ] 最終訓練流程（資料增強、cross-validation 等）
- [ ] A 與 B 的最終建議閾值
- [ ] 對抗繞過攻擊（adaptive attack）的測試設計

---

## 參考文獻

- **RAGuard (2025)**：非參數化多階段過濾，PPL Filtering 思路
- **PoisonedRAG (2024)**：雙目標最佳化，攻擊文本特徵分析
- 其他文獻待補（依最終方法論調整）
