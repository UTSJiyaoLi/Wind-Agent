# BGE Reranker v2 调优经验总结

有，而且方向已经很明确：**不是继续扩大召回，而是把 top20 里的正确结果再往前推。**

你开了 `bge reranker v2` 之后：

- Recall@5：**0.5417 → 0.6250**
- Recall@10：**0.5417 → 0.6667**
- Recall@20：**0.8750 → 0.8750**

这说明 reranker **有效改善了前排排序**，但**底层召回集合没变**。也就是说，当前瓶颈已经从“找不到”变成了“前 10 还不够强”。这和 reranker 的定位一致：它是在第一阶段检索之后，对候选结果做更深入的相关性重排，而不是提升底层候选覆盖。

最值得做的是下面这几项。

## 第一，先把 rerank 的候选池调对

BGE 官方示例就是“先检索 top 100，再重排，最后取 top 3”，FlagEmbedding 也明确建议把 reranker 用在 embedding/检索阶段返回的 top-k 候选上。你的 `Recall@20` 已经不低，所以现在最该试的是：**固定最终给 LLM 的条数不变，但把 rerank 输入候选数做 AB test**，例如：

- 检索 20 → rerank 20 → 取前 5
- 检索 30 → rerank 30 → 取前 5
- 检索 50 → rerank 30 → 取前 5

如果你现在 rerank 的只是前 10 或前 20，很可能候选池太小，导致正确块虽然能进 top20，但没有足够上下文让重排器把它抬进 top5。官方示例里 top100 只是展示思路，不是必须照搬；你的场景更适合试 20/30/50 这些更现实的范围。

## 第二，去重一定要在 rerank 前做，而且尽量按文档窗口去重

你现在的问题很像“前排被同文档相似块占住”。这会让 cross-encoder 把很多近似片段都判成相关，结果真正最关键的块还在后面。做法是：

- 先按 `doc_id` 或 `doc_id + page/window` 去重
- 每篇文档只保留若干代表块进 rerank
- rerank 后再决定是否补邻块给 LLM

这样常常比单纯换更大的 reranker 更有效。Milvus 的 reranking 文档本身也把 reranking 放在第一阶段召回之后，意味着前面候选集的质量和冗余控制会直接影响重排效果。

## 第三，检查 chunk 粒度，BGE reranker 对“过长或过碎”都不友好

reranker 输入是 query + passage，直接输出相关性分数，不是 embedding。太长的 chunk 会把关键信息稀释，太碎的 chunk 又会缺语义闭环，都会导致真正相关块排不够前。BGE 官方说明 reranker 直接对 query 和 passage 打分，因此输入 passage 的组织方式会直接影响分数。

你可以试两档：

- 300 到 500 tokens
- 500 到 800 tokens

然后看 `Recall@5/10` 和 MRR 哪档更好。

如果你的块里经常混很多表格引用、图片说明、长 metadata，也建议先清掉这些噪声字段，只把“适合重排的正文摘要”送进 reranker。

## 第四，减少 query augmentation 的噪声，再让 reranker 接手

你前面的指标模式很像：底层召回能到 20，但前排排序受噪声影响。很常见的原因是 rewrite / domain expansion 把“泛相关块”也拉进来了。RRF 会把这些在多个分支都不差的块抬高，随后 reranker 再去纠偏，但纠偏能力是有限的。Milvus 对 hybrid search 和 RRF 的说明也是：它是在多路搜索结果之上做融合；融合前的各分支质量会影响最终排序。

一个很有效的实验是分别跑：

- 原 query
- 原 query + rewrite
- 原 query + rewrite + domain expansion

然后都接同一个 reranker，看哪种组合的 `Recall@5/10` 最好。

很多系统最后发现：**少一点扩展，反而前排更好。**

## 第五，换更适合你语料的 v2 变体，别只盯“更大”

BGE v2 家族里，`bge-reranker-v2-m3` 是面向多语言场景的；模型卡还特别提到它适合 multilingual，并且对中英文都表现较好。若你的语料有中文、英文、日文混合，`v2-m3` 往往比单语取向更稳。另一个 `bge-reranker-v2-minicpm-layerwise` 支持按层输出，方便做加速与效果折中。

所以你可以这么试：

- 当前模型 vs `bge-reranker-v2-m3`
- 如果速度压力大，再试 `v2-minicpm-layerwise` 的较浅层输出

如果你现在已经是 `v2-m3`，那重点就别放在换模型，而是放在候选池、去重和 chunk。

## 第六，重排输入文本要“干净”

很多时候 reranker 效果差，不是模型不行，而是传给它的 passage 太脏，比如：

- 带大段路径、表格标记、媒体引用
- 混了标题、正文、页脚、引用索引
- 一个 chunk 里拼了太多不同语义段

BGE reranker 是直接对 query-passage 打分，不像 embedding 那样对噪声有时还能“平均掉”。

建议你送给 reranker 的内容尽量是：

- 标题 + 核心正文
- 不要完整 metadata JSON
- 不要大段图片/表格引用路径
- 长表格先摘要再送

## 第七，别只看 Recall，再加一个 MRR 或 nDCG@10

你现在最需要优化的是“排得更前”，所以 `Recall@20` 已经不再是最关键指标。更该看：

- MRR
- nDCG@10
- rerank 前后 rank 位移
- 正确块落在 1 到 5、6 到 10、11 到 20 的分布

这样你能知道 reranker 到底是在“微调”，还是已经把大量正确块从 15 名抬到 3 名。

## 建议的实验顺序

我会建议你按这个顺序做实验，成本最低：

1. **rerank 候选池**：20 / 30 / 50
2. **去重策略**：不去重 / doc 去重 / doc+window 去重
3. **chunk 长度**：短块 vs 中块
4. **query augmentation 组合**：原 query vs rewrite vs rewrite+expansion
5. **模型变体**：当前 v2 vs v2-m3

如果只能先做一件事，我建议先做这个：

**检索 30，先按 doc+window 去重到 15~20，再用 BGE reranker v2 重排，最后取前 5。**

这通常比“直接把 rerank 输入从 20 拉到 100”更划算，因为它先去掉了相似噪声。

## 总结

你这组数据已经说明 reranker 路线是对的。下一步不是再盲目扩大 topK，而是把 **候选池质量、去重位置、chunk 组织方式** 调顺。这样最容易把 `Recall@5` 再往上推。
