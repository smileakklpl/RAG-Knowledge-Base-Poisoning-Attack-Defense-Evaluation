# Defense for RAG Poisoning Attack 方法論 (檢索後)

---

> 檢索前防禦目前查到比較偏向文件是人類還是AI產生,利用perplexity去評估 (PPL越高越不合理)
> 

# 1. 反事實檢測

**論文**：ContextCite: Attributing Model Generation to Context（NeurIPS 2024）

[https://proceedings.neurips.cc/paper_files/paper/2024/file/adbea136219b64db96a9941e4249a857-Paper-Conference.pdf](https://proceedings.neurips.cc/paper_files/paper/2024/file/adbea136219b64db96a9941e4249a857-Paper-Conference.pdf)

## 核心問題

當 LLM 根據 RAG 檢索結果生成回答時，我們無法直接知道：

- 這句話到底是由哪個 chunk 引發的？
- model 是在使用 context，還是在用 pretrain 知識？
- 有沒有哪個 chunk 被惡意注入並影響了輸出？

ContextCite 解決的就是這個「context attribution」問題：**把 LLM 生成的某句話，追溯回 context 中真正導致它的 source chunk。**

## 方法論

ContextCite 的本質是學一個**線性 surrogate model**，來近似「某個 source chunk 被拿掉後，LLM 輸出機率的變化量」。

**重要前提**：attribution score 高 ≠ 資訊正確，而是代表「model 確實用了這個 source 來生成這句話」。

| score 狀況 | 意義 |
| --- | --- |
| score 高 + source 內容正確 | 回答可信，有根據 |
| score 高 + source 是惡意注入 | 被攻擊，model 被劫持 |
| score 低 | model 沒用這個 source（來自 pretrain 知識，或完全不相關） |

**流程（共 3 步）**：

1. 從 context 的 $d$ 個 sources 中，隨機 sample $n$ 個 ablation vector v in  {0,1}$^d$（每個 vector 決定哪些 sources 被移除）
2. 對每個 ablation，跑一次 inference，記錄 response 的 logit-scale 機率
3. 用 LASSO 對 `(ablation vector, logit-prob)` 做 sparse linear regression，回歸出來的**權重**直接當 attribution score

**公式**：

目標函數定義為：

$f(v) := p_{LM}(R \mid \text{ABLATE}(C, v), Q)$

因機率值有界於 [0,1]，改用 logit 轉換為 target：

$g(v) := \sigma^{-1}(f(v)) = \log \frac{f(v)}{1 - f(v)}$

LASSO 回歸（L1 正則化）：

$\min_w \sum_{i=1}^n (y_i - w^T v_i)^2 + \lambda \|w\|_1$

L1 懲罰讓大部分 $w_j$ 變成 0，只有真正影響 response 的少數 source 有非零權重。輸出的 $\hat{w}_j$ 代表「把第 $j$ 個 source 加回來，response 的 logit-probability 預期增加多少」。

**為何只需 32 次 ablation 就夠？**

實際影響 response 的 source 很少（sparse），根據 sparse linear regression 理論只需 $O(k \log d)$ 個 sample，其中 $k$ 是非零 source 的數量，遠小於 $d$。

## ContextCite 的操作時間點

ContextCite 是**完全 post-hoc**，必須等 LLM 輸出之後才能運作：

```
chunks → [LLM Inference] → response → [ContextCite 分析] → attribution scores
```

計算代價約為原始 inference 的 **32 倍**（32 次 ablation inference）。

## 對三種攻擊的預期效果

| 攻擊類型 | Score 是否異常高 | 原因 |
| --- | --- | --- |
| Instruction hijack | ✅ 高 | 直接覆蓋 response，惡意 chunk 對輸出的影響極大且集中 |
| Blocker / DoS | ✅ 高 | 讓 model 拒絕回答，同樣是強烈且集中的影響 |
| Semantic stealth | ⚠️ 不確定 | 故意模仿正常語意，影響可能分散，無法靠排名找出來 |

**Semantic stealth 是這個方法最大的 limitation**，惡意 chunk 的 score 可能跟正常 source 差不多，偵測失效。這可以作為我們自己防禦設計的 motivation。

---

# 2. 多 Chunk 一致性投票

**論文**：Certifiably Robust RAG against Retrieval Corruption（2024）

[https://arxiv.org/pdf/2405.15556](https://arxiv.org/pdf/2405.15556)

## 核心問題

Vanilla RAG 把所有 retrieved passages 直接串接給 model，只要其中一個是惡意的，整個 response 就可能被劫持。RobustRAG 提出第一個具有**可認證 robustness** 的防禦框架。

## 核心策略：Isolate-then-Aggregate

**不把所有 passages 一起餵給 model**，而是：

1. 將 $k$ 個 passages 均勻切割成 $g$ 個 disjoint groups
2. 對每個 group 分別讓 **同一個 LLM** 產生獨立 response（共跑 $g$ 次 inference）
3. 將 $g$ 個 isolated responses 安全聚合成最終輸出

![image.png](image.png)

**Certifiable robustness 的數學保證**：

只要惡意 passages 數量 $t$ 滿足：

$t < \frac{g}{2}$

就能保證多數的 isolated responses 是乾淨的，多數決機制可以壓制攻擊。

**範例**（k=6, g=3）：

```
Group1: [p1, p2] → LLM → response_1  (正常)
Group2: [p3, p4] → LLM → response_2  (正常)
Group3: [p5, p6] → LLM → response_3  (被污染 ← 惡意 chunk 在這裡)
                              ↓
                         Aggregate → 多數決 → 最終輸出
```

**注意**：分組是機械式均勻切割，**不考慮語意**，這是這個方法的弱點之一（見下方 limitation）。

## 兩種 Aggregation 方法

### Keyword-based Aggregation

操作在 **LLM 輸出之後**（共需跑 $g+1$ 次 inference）：

1. 從每個 isolated response 抽取 unique keywords
2. 跨所有 responses 統計 keyword 出現次數（每個 response 每個 keyword 只計 1 次）
3. 只保留出現次數超過閾值 $\alpha$ （預設 0.5，即超過一半 responses 都出現）的 keywords
4. 用篩選後的 keywords 再 prompt LLM 一次 → 最終 response

![image.png](image%201.png)

**Limitation**：答案很長或複雜時資訊損失大，因為最終只基於少數 keywords。

### Decoding-based Aggregation

操作在 **LLM decoding 過程中**（干預 LLM 內部運作，需要存取 logits）：

1. 每個 decoding step，每個 group 分別預測下一個 token 的**機率分布**
2. 把所有 group 的機率向量聚合（如取平均或中位數）
3. 根據聚合後的分布選出下一個 token，設有 confidence threshold

![image.png](image%202.png)

由於機率值被限制在 [0,1]，攻擊者**無法任意操控**聚合後的結果。

## 兩種方法比較

|  | Keyword-based | Decoding-based |
| --- | --- | --- |
| 操作位置 | LLM 輸出後 | LLM decoding 過程中 |
| 需要存取 logits | ❌ Black-box 即可 | ✅ 需要存取 logits |
| 適合長文本 | ❌ 資訊損失大 | ✅ 較好 |
| 實作難度 | 低 | 高 |

| 攻擊類型 | Keyword-based | Decoding-based | 原因 |
| --- | --- | --- | --- |
| Instruction hijack | ✅ 有效 | ✅ 有效 | 惡意 chunk 只污染少數 group，keywords 投票或機率聚合都能壓制 |
| Blocker / DoS | ✅ 有效 | ✅ 有效 | 拒絕回答的 response 是少數，多數 group 仍正常，聚合後被壓制 |
| Semantic stealth | ⚠️ 部分有效 | ⚠️ 部分有效 | 惡意 chunk 語意接近正常，但只要惡意 chunk 數量 < g/2，理論上仍可壓制；問題在於 semantic stealth 可能同時注入多個相似 chunk 分散到不同 group，突破門檻 |

## 三種方法的處理位置比較

```
[Chunk 階段]   →   [LLM Decoding 中]   →   [LLM 輸出後]

我們想做的           RobustRAG                RobustRAG
chunk 一致性      (Decoding-based)          (Keyword-based)
pre-filter                                   ContextCite
```

## Limitation 與我們的切入點

RobustRAG 的分組是機械式切割，**不考慮語意關係**。攻擊者若注入多個語意相似但措辭不同的惡意 passages，分散到不同 group，就能突破 $t < g/2$ 的門檻。

**我們的 chunk 層面一致性過濾**可以在進入 RobustRAG 之前先淘汰可疑 chunk，讓送進去的 passages 本身更乾淨，兩者形成互補。