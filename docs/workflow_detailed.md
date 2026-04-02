# MinerU 文档解析到 Chunking 全流程说明

## 1. 文档目标

这份说明基于 `parse_mineru_v2_core.py` 的实现逻辑整理，覆盖从 **PDF parsing** 到 **chunking**、再到 **JSONL 输出** 的完整链路。重点不是只解释“代码做了什么”，而是说明：

1. 输入的 PDF 如何被 MinerU 解析。
2. 解析结果如何被整理成页面级结构。
3. 页面文本如何被清洗、过滤和结构化。
4. 如何从 page-level 文本继续切成 parent / child chunk。
5. 图像、表格、公式信息如何与文本 chunk 关联。
6. 最终输出的数据格式、元数据字段与适用场景。

---

## 2. 当前系统里实际涉及的解析组件

结合你前面给出的服务器目录，可以把这一套系统理解成两层：

### 2.1 第一层：文档结构解析主流程

你当前代码不是直接手写 PDF 解析，而是通过命令行调用：

- `mineru`
- 或 `magic-pdf`

也就是说，这个 Python 文件本质上是 **MinerU 的上层封装器 / 后处理器**。

### 2.2 第二层：底层 OCR / 文档识别模型

根据你之前给出的模型目录，当前服务端大概率使用的是：

- `PDF-Extract-Kit-1.0`
- `PP-OCRv5_det`
- `PP-OCRv5_rec`
- `PP-OCRv4_rec_server_doc`

因此，整体可以理解为：

- **MinerU / Magic-PDF**：负责 PDF 文档理解与版面抽取
- **PaddleOCR 系列模型**：负责文本检测与识别
- **当前 Python 文件**：负责把解析输出加工成更适合 RAG / 检索 / 向量库的数据

> 注意：`parse_mineru_v2_core.py` 本身并没有显式写死具体 OCR 模型文件名，它调用的是已安装好的 MinerU 可执行程序，因此“具体模型名称”是从你服务器目录推断出来的，不是这份代码里硬编码的。

---

## 3. 整体流程总览

这份脚本的主流程可以概括为：

```text
PDF
  -> 调用 MinerU / magic-pdf
  -> 生成 content_list.json
  -> 读取 block 列表
  -> 按页归并 page buffers
  -> 提取文本 / 图像 / 表格 / 公式
  -> 文本清洗与噪声过滤
  -> 生成 page-level Document
  -> 语义分组（semantic grouping）
  -> 合并成 parent chunks
  -> 再切成 child chunks
  -> 关联附近的图像 / 表格 / 公式元数据
  -> 写出 JSONL
```

如果你的目标是做知识库、RAG、检索增强问答，这个设计是比较合理的，因为它把“解析”和“索引粒度设计”拆成了两个阶段：

- **阶段 A：Parsing** —— 把 PDF 变成可用结构
- **阶段 B：Chunking** —— 把结构变成适合检索的数据单元

---

## 4. 配置参数解释

脚本里定义了一组关键常量：

### 4.1 chunk 尺寸相关

- `PARENT_CHUNK_SIZE = 800`
- `CHILD_CHUNK_SIZE = 250`
- `CHILD_CHUNK_OVERLAP = 80`
- `SEMANTIC_GROUP_SIZE = 15`

含义如下：

#### Parent chunk

Parent chunk 更偏向“语义上完整的一段”，用于保留上下文。它的目标大小是 **800 tokens** 左右。

#### Child chunk

Child chunk 更偏向实际检索粒度。它的目标大小是 **250 tokens**，并带有 **80 tokens overlap**，这样在检索时既足够细，又不会把跨句语义切断太严重。

#### Semantic group

先按句子切分，再每 **15 句** 做一个初步语义组。这个组不一定直接成为最终 parent chunk，还会继续合并到不超过 `PARENT_CHUNK_SIZE`。

### 4.2 过滤阈值

- `MIN_PARENT_TOKENS = 80`
- `MIN_PARENT_CHARS = 120`
- `MIN_PARENT_SENTENCES = 2`
- `MIN_CHILD_TOKENS = 40`
- `MIN_CHILD_CHARS = 80`

作用是避免留下太短、太碎、信息密度过低的 chunk。

### 4.3 页面与视觉元素限制

- `MIN_FILTER_PAGES = 0`
- `MAX_FILTER_PAGES = 100000`
- `MAX_VISUALS_PER_CHUNK = 4`
- `MAX_EQUATIONS_PER_CHUNK = 4`
- `NEAREST_BLOCK_DISTANCE = 4`

这几个参数用于控制：

- 处理哪些页
- 每个 chunk 最多挂载多少图像/表格
- 每个 chunk 最多挂载多少公式
- 关联视觉元素时，允许的最近 block 距离

---

## 5. Parsing 阶段：如何调用 MinerU

### 5.1 查找执行命令

脚本会先找系统里是否存在：

- `mineru`
- `magic-pdf`

找到哪个就调用哪个。

这表示代码设计成了 **兼容两种命令名**，但实际底层本质仍然是 MinerU 这一套。

### 5.2 运行方式

在 `_run_mineru()` 中，代码大致做了这些事：

1. 建一个临时目录。
2. 把源 PDF 软链接或复制为 `input.pdf`。
3. 调用 MinerU 命令行。
4. 指定输出目录。
5. 在输出目录中搜索 `*_content_list.json`。
6. 找到后返回这个 JSON 文件路径。

### 5.3 CLI 参数含义

命令构造大致是：

```bash
mineru -p input.pdf -o output_dir -b pipeline -m auto -f true -t true
```

字段说明：

- `-p`：输入 PDF
- `-o`：输出目录
- `-b pipeline`：后端模式，当前默认 `pipeline`
- `-m auto`：解析方式默认自动选择
- `-f true`
- `-t true`

最后两个参数的具体语义取决于你所安装的 MinerU 版本，但从整体行为上看，它们是在要求生成更完整的解析产物。

### 5.4 页码范围控制

如果传了：

- `start_page`
- `max_pages`

那么会计算出 `mineru_end_page`，并转成 CLI 的：

- `-s` 起始页
- `-e` 结束页

注意代码里是按 **0-based** 页索引传给 MinerU，但对外部 metadata 又会恢复成 **1-based** 页码。

---

## 6. MinerU 输出的核心中间格式：content_list

MinerU 解析完成后，脚本期待得到一个 `content_list.json`。它应当是一个 `list[dict]`，每个元素代表一个 block。

一个 block 通常可能包含：

- `type`
- `page_idx` 或 `page_no`
- `bbox`
- `text`
- `content`
- `latex`
- `table_caption`
- `table_body`
- `table_footnote`
- `html`
- `image_caption`
- `image_footnote`
- `img_path`

也就是说，这份 JSON 并不是纯文本，而是 **混合布局块列表**。

---

## 7. Block 级抽取逻辑

### 7.1 文本块

如果 block type 是：

- `text`
- `title`

就优先取：

- `text`
- 否则 `content`

### 7.2 公式块

如果 block type 是：

- `equation`
- `interline_equation`

就优先取：

- `latex`
- 如果没有，再取普通文本

这说明公式在系统里是被当成“可检索文本”的，不只是一个视觉对象。

### 7.3 表格块

对于 `table`，代码会拼接：

- `table_caption`
- `table_body`
- `table_footnote`
- `html`
- `text`

所以表格既有“表题/脚注”，也可能保留 HTML 或正文文本形式。对于 RAG 来说，这样做的好处是：

- 表格内容能被文本检索命中
- 表格标题与表体不会完全丢失关联

### 7.4 图像块

对于 `image`，代码会拼接：

- `image_caption`
- `image_footnote`
- `text`

图像本身不直接转成视觉 embedding，而是先把图片的说明性文本收集起来，同时尝试复制原始图片文件到资产目录。

---

## 8. 页码与坐标处理

### 8.1 页码归一化

`_normalize_page_idx()` 会优先读：

- `page_idx`
- 如果没有，再读 `page_no`

并最终统一成内部使用的 page index。

### 8.2 bbox 处理

`_bbox_as_list()` 会把 block 的 bbox 统一成长度为 4 的浮点列表，并保留两位小数。

这样后续如果你要做：

- 可视化高亮
- 坐标回溯
- chunk 对应页面区域定位

就有基础数据可用。

---

## 9. 按页构建 page buffers

`_build_page_documents()` 是 parsing 后处理的关键函数。

它会把同一页的 block 收集到一个 `page_buffers` 里，每一页维护以下信息：

- `blocks`
- `figures_info`
- `tables_info`
- `equations_info`
- `image_refs`
- `table_refs`

这一步非常重要，因为 MinerU 原始输出常常是“全局 block 列表”，而实际做知识库时，我们更需要“按页组织”的中间表示。

### 9.1 blocks

存真正进入正文序列的文字块，包括：

- 文本
- 标题
- 公式（作为文本）

### 9.2 figures_info

对于每张图，会记录：

- kind = figure
- page / page_no
- title
- caption
- footnote
- bbox
- block_index
- source_rel_path
- asset_path
- order_on_page

### 9.3 tables_info

对于每张表，会记录：

- kind = table
- page / page_no
- title
- caption
- footnote
- bbox
- html
- block_index
- order_on_page

### 9.4 equations_info

对于公式，会记录：

- kind = equation
- page / page_no
- title
- formula_text
- formula_latex
- bbox
- block_index
- equation_type
- order_on_page

这说明系统并没有丢弃公式，而是把它作为独立知识对象挂在 page metadata 里。

---

## 10. 资产文件复制策略

图像类 block 如果有相对路径，就会通过 `_copy_asset()` 把实际文件复制到：

```text
asset_save_dir / "images"
```

这样做有几个实际价值：

1. 解析结束后，资产不会只留在 MinerU 的临时目录里。
2. 后续检索结果可以返回对应图像路径。
3. 可以做多模态扩展，比如点击 chunk 后再展示原图。

当前代码对表格没有复制文件，而是偏向把表格内容保存为 HTML / text。

---

## 11. 文本清洗（cleaning）策略

在真正进入 chunking 之前，代码做了多层清洗。

### 11.1 基础清洗：`clean_text()`

主要处理：

- 替换不间断空格 `\u00a0`
- 去除零宽字符 `\u200b`
- 合并多余空格
- 把连续 3 个以上换行压缩为 2 个
- 去掉首尾空白

### 11.2 句子切分：`sentence_split()`

支持中英文混合分句，主要依据：

- `。！？；`
- `. ! ? ;`
- 换行

这为后面的 semantic chunk 提供了基础。

### 11.3 语言识别：`detect_lang()`

通过字符统计做轻量语言判断：

- 日文 kana → `ja`
- 汉字为主 → `zh`
- 英文字符为主 → `en`

这不是高精语言识别器，但足够用于文档级 metadata 标记。

---

## 12. 噪声过滤策略

这一部分非常实用，尤其适合学术 PDF、出版物 PDF。

### 12.1 完全噪声匹配

`NOISE_FULL_PATTERNS` 会直接删掉整行，例如：

- 单独页码
- `page 12`
- `springer-verlag`
- 单独 DOI / URL
- `all rights reserved`
- `copyright ...`

### 12.2 部分噪声替换

`NOISE_PARTIAL_PATTERNS` 会删除文本中的局部噪声，比如：

- `available online`
- DOI
- URL
- 出版社水印类字段

### 12.3 作者行识别

`is_probable_author_line()` 会尝试识别作者名单风格的行，例如：

- 多个首字母大写姓名
- 含逗号 / and / 分号连接的作者串

这类行通常不适合作为知识检索内容，因此会被过滤掉。

### 12.4 参考文献截断

`truncate_before_references()` 遇到这些标题会直接停止保留后续内容：

- `references`
- `bibliography`
- `acknowledgements`

也就是说，**从 references 开始整段都不要**。

这是一个非常明确的知识库策略：

- 保正文
- 丢参考文献
- 丢致谢

这样可以显著减少无意义检索噪声。

### 12.5 页面级过滤函数

`filter_page_lines()` 的顺序是：

1. 先截断参考文献之后的内容
2. 再去掉局部噪声
3. 再判断整行是不是噪声
4. 剩下的作为页面正文

---

## 13. page-level Document 的构建

每一页最终会被整理成一个 LangChain `Document`。其 `page_content` 是：

```text
clean_text("\n\n".join(filtered_lines))
```

也就是：

- 取该页所有保留的正文行
- 用双换行拼起来
- 再整体清洗一次

### 13.1 page metadata 包含什么

一页的 metadata 非常丰富，主要有：

- `unique_id`
- `doc_id`
- `source`
- `source_file`
- `source_path`
- `page`
- `page_no`
- `lang`
- `doc_lang`
- `parser`
- `content_type`
- `chunk_level = page`
- `token_count`
- `text_hash`
- `block_count`
- `filtered_line_count`
- `image_refs`
- `table_refs`
- `figures_info`
- `tables_info`
- `visuals_info`
- `equations_info`
- `has_formula`

这意味着 page-level 并不是只有文字，而是一个“带多模态附属信息的页面对象”。

### 13.2 文档级语言统一

虽然每页先单独检测语言，但最后会用所有页投票，取众数作为整个文档的 `doc_lang`，并覆盖每页的 `lang`。

所以最终的 page docs 在语言字段上趋向文档级统一，而不是逐页漂移。

---

## 14. 为什么先做 page，再做 chunk

这是这份代码很合理的一点。

如果你一开始就直接全局切 chunk，会失去几个重要信息：

1. 页码归属
2. 图表与公式相邻关系
3. 页面局部噪声过滤能力
4. 页面级回溯能力

先做 page-level 文档，再从 page-level 继续切 parent/child chunk，会让检索和溯源都更稳。

---

## 15. Chunking 阶段总览

`texts_split()` 负责从 page docs 生成 chunk docs。

这个函数不是简单按固定长度切，而是一个 **两级 chunking 结构**：

```text
page doc
  -> semantic grouping
  -> parent chunks
  -> child chunks
```

这样设计的目标通常是：

- parent 用于保留上下文与聚合视觉信息
- child 用于实际检索召回

---

## 16. 第一步：semantic grouping

默认使用 `default_semantic_chunk()`。

它会：

1. 先用 `sentence_split()` 分句
2. 每 `SEMANTIC_GROUP_SIZE = 15` 句合并成一个组

所以这个阶段不是 token-based，而是 **句子组**。

这么做的好处是：

- 先尽量按语义自然边界切
- 再考虑 token 大小
- 减少硬切在句子中间的问题

这个函数还支持外部传入 `semantic_chunk_fn`，说明以后你可以替换成更高级的策略，比如：

- 标题感知 chunking
- embedding 相似度断点 chunking
- rule-based section chunking

---

## 17. 第二步：构建 parent chunks

得到句子组后，代码并不会直接把每组作为 parent chunk，而是继续合并，直到接近：

- `PARENT_CHUNK_SIZE = 800 tokens`

逻辑是：

- 如果当前 buffer 再加一个 group 会超过 800 tokens，先把 buffer 输出成一个 parent
- 否则继续往 buffer 里加

所以 parent chunk 实际是：

- **多个 semantic groups 的合并结果**
- **大小受 token 上限控制**
- **尽量保持语义连续**

### 17.1 parent chunk 的有效性判断

`is_valid_parent_text()` 要求至少满足之一：

- token 数 >= 80
- 字符数 >= 120
- 句子数 >= 2

这能避免产生标题碎片、公式碎片、残缺页脚等无效 parent。

---

## 18. Parent chunk 如何关联视觉对象和公式

这部分是代码里一个很有价值的设计。

### 18.1 邻近项选择函数

`_pick_nearby_items()` 会根据 block index 的距离，挑选离当前 chunk 最近的：

- 图像 / 表格
- 公式

并且受这些参数限制：

- 图表最多 4 个
- 公式最多 4 个
- 距离超过 `NEAREST_BLOCK_DISTANCE = 4` 时，如果已经选到一些对象，就停止继续扩张

### 18.2 实际效果

这意味着每个 parent chunk 不只是文本本身，还会在 metadata 里额外挂：

- `related_visuals`
- `related_equations`
- `related_figure_titles`
- `related_table_titles`
- `equation_titles`
- `has_formula`

这个设计很适合问答场景。例如用户问：

- “图 2 说明了什么？”
- “表 3 中的实验结果是什么？”
- “这个公式附近在讲什么？”

系统就能通过 chunk metadata 找到局部相关对象，而不是只靠纯文本召回。

---

## 19. Parent metadata 设计

每个 parent chunk 会生成：

- `unique_id`
- `chunk_id`
- `parent_id = None`
- `chunk_level = parent`
- `group_index`
- `token_count`
- `text_hash`
- `retrieval_enabled`
- 以及前面提到的一组 related visuals / equations 字段

其中：

- `parent_id = None`：因为 parent 是上层 chunk
- `retrieval_enabled = include_parents`

也就是说，parent 是否参与检索是可配置的。

如果 `include_parents=False`，一般 parent 只作为结构中间层存在；如果设为 True，则 parent 也能直接进索引。

---

## 20. 第三步：切 child chunks

在 parent chunk 下面，代码再调用 `TEXT_SPLITTER.create_documents()` 切 child。

这里使用的是 LangChain 的 `RecursiveCharacterTextSplitter`，但长度函数不是按字符算，而是：

- 优先用 `tiktoken` 统计 token
- 没有编码器时，退化为按空格分词数估计

### 20.1 child splitter 参数

- `chunk_size = 250`
- `chunk_overlap = 80`

分隔符顺序是：

1. 双换行
2. 单换行
3. 中文句号/感叹号/问号
4. 英文句号/感叹号/问号
5. 分号
6. 逗号
7. 空格
8. 空串

这说明 child 切分会尽量优先在更自然的边界断开。

### 20.2 child 的有效性判断

`is_valid_child_text()` 要求至少满足之一：

- token 数 >= 40
- 字符数 >= 80

此外还有一个额外约束：

- 如果 child_text == group_text 且其 token 数本来就 <= 250，则跳过这个 child

原因是：这种情况通常说明“这个 parent 没必要再细分”，避免重复生成内容相同的 child。

---

## 21. fallback child 机制

如果某个 parent chunk 切完后，一个合法 child 都没产出，但 parent 本身又满足 child 最低门槛，就会创建一个 fallback child：

- 内容直接等于 parent text
- `child_index = 0`

这个机制很重要，因为它避免出现：

- parent 有内容
- 但 child 全被过滤掉
- 最终该段内容根本进不了索引

换句话说，它保证了召回层不会意外“漏段”。

---

## 22. Child metadata 设计

每个 child chunk 会继承 parent metadata，并覆盖 / 增加：

- `unique_id`
- `chunk_id`
- `parent_id = parent chunk id`
- `chunk_level = child`
- `child_index`
- `token_count`
- `text_hash`
- `retrieval_enabled = True`

这说明：

- child 是默认检索主力
- parent-child 之间通过 `parent_id` 建立层级关系

后续你做检索增强时，可以：

1. 向量库检索 child
2. 命中后通过 `parent_id` 回溯更大的上下文
3. 再把 related visuals / equations 一起带回给 LLM

这是一个很典型也很有效的 hierarchical retrieval 方案。

---

## 23. 输出结构：include_parents 的意义

`texts_split()` 最后有两种返回方式：

### 23.1 `include_parents = False`

只返回 child docs。

适合：

- 只构建细粒度向量索引
- 检索时不直接使用 parent

### 23.2 `include_parents = True`

返回：

- `parent_docs + child_docs`

适合：

- 同时索引两层粒度
- 或把 parent 存到单独表 / 单独集合

在很多 RAG 系统里，这两层会分开存：

- child：向量召回
- parent：命中后扩展上下文

---

## 24. 唯一 ID 与稳定性设计

整个系统大量使用 `stable_id()`，本质是对输入字段拼接后做 MD5。

它被用于：

- page 级 `unique_id`
- parent `chunk_id`
- child `chunk_id`
- `text_hash`

好处：

1. 同样内容再次跑，ID 相对稳定。
2. 方便去重。
3. 方便增量更新。
4. 方便父子映射。

不过也要注意：

- 只要文本有细微变动，hash 就会变化。
- 如果 MinerU 版本升级导致 OCR 文本略变，ID 也会变。

因此它是“内容稳定 ID”，不是“文档固有永久 ID”。

---

## 25. 输出 JSONL 的方式

有两个输出函数：

### 25.1 `write_langchain_jsonl()`

覆盖写入。

### 25.2 `append_langchain_jsonl()`

追加写入。

每一行格式为：

```json
{
  "page_content": "...",
  "metadata": {
    "unique_id": "...",
    "doc_id": "...",
    "source_path": "...",
    "page": 1,
    "lang": "en",
    "chunk_id": "...",
    "parent_id": "...",
    "chunk_level": "child",
    "parser": "mineru-gpu"
  }
}
```

注意一个细节：最终输出前会调用 `sanitize_output_metadata()`，只保留少数字段：

- `unique_id`
- `doc_id`
- `source_path`
- `page`
- `lang`
- `chunk_id`
- `parent_id`
- `chunk_level`
- 外加 `parser = mineru-gpu`

也就是说，很多丰富 metadata（例如 figures_info、equations_info）**在当前 JSONL 输出里并不会保留下来**。

这点非常关键。

### 25.3 这意味着什么

如果你现在直接把 JSONL 送进向量库，最终索引里只会保留“简化元数据”。

因此：

- 如果你想在检索阶段用到图表/公式信息
- 或想做页面坐标回溯
- 或想展示图片资产路径

你需要修改 `sanitize_output_metadata()`，把更多字段加入 `OUTPUT_METADATA_KEEP_KEYS`。

这是这份代码目前一个很明显的“功能保守点”。

---

## 26. 摘要统计函数

`summarize_docs()` 只针对 `chunk_level == page` 的文档做统计，输出：

- 页数 / page docs 数量
- 页码集合
- figure 数量
- table 数量
- equation 数量

它适合在 pipeline 跑完后快速检查：

- 哪些页被保留下来了
- 图表和公式是否被解析到

---

## 27. 方法论评价：这套 parsing + chunking 方案的优点

### 27.1 优点一：结构分层清楚

不是把 PDF 一把梭切碎，而是：

- block
- page
- parent
- child

这使得每层都有清晰职责。

### 27.2 优点二：适合 RAG

特别适用于知识库问答，因为它同时考虑了：

- 召回粒度
- 上下文恢复
- 页码追踪
- 视觉对象关联

### 27.3 优点三：对学术 PDF 友好

参考文献截断、作者行过滤、URL/DOI 清洗，对论文类 PDF 非常有效。

### 27.4 优点四：兼顾多模态扩展

虽然当前输出主要还是文本索引，但 page metadata 已经把：

- 图
- 表
- 公式
- 资产路径

都挂好了，后面要扩展成多模态系统会比从零做轻松很多。

---

## 28. 当前方案的局限

### 28.1 局限一：semantic grouping 仍然比较粗糙

现在只是“每 15 句一组”，没有显式利用：

- 标题层级
- section 边界
- 列布局变化
- 表格/图注边界

这会导致某些 chunk 边界还不够“文档结构感知”。

### 28.2 局限二：视觉信息在最终 JSONL 中被裁掉了

代码中 page docs 和 parent docs 的 metadata 很丰富，但 `sanitize_output_metadata()` 输出时删掉了很多字段。

如果不改，后续检索阶段无法直接使用这些结构信息。

### 28.3 局限三：block_index 与 group_index 不完全同尺度

当前 `_pick_nearby_items()` 用 block index 和 group index + semantic_group_size 做近邻匹配，这在多数情况下能工作，但严格来说：

- group_index 是 parent 序号
- block_index 是页面 block 序号

二者并不是完全同一量纲。

在文档复杂时，邻近匹配可能不够精确。更稳妥的方法是：

- 记录每个 parent chunk 覆盖的原始 block 范围
- 再按这个范围找图表/公式

### 28.4 局限四：语言识别较轻量

`detect_lang()` 是字符级启发式规则，对中英混排、术语多、数学公式多的文档不一定稳定。

---

## 29. 我建议你后续优化的方向

### 29.1 优先优化输出元数据

这是最值得先改的地方。

建议把这些字段保留到 JSONL：

- `page_no`
- `token_count`
- `text_hash`
- `has_formula`
- `related_figure_titles`
- `related_table_titles`
- `equation_titles`
- `image_refs`
- `table_refs`
- `figures_info`
- `tables_info`
- `equations_info`

如果担心 metadata 太大，可以至少保留标题级摘要字段，而不是全量删除。

### 29.2 用标题感知 chunking 替代纯句子分组

例如：

- 遇到标题优先断 chunk
- 遇到表格标题 / 图注单独成组
- section 内部再做 token 限制

这样 chunk 会更接近人类阅读结构。

### 29.3 区分不同文档类型

不同 PDF 类型可以用不同策略：

- 论文：强过滤 references
- 报告：保留图表和摘要
- 合同：保留条款编号
- 手册：按标题层级切块

### 29.4 引入 parent-child 双索引

如果你现在还没正式做索引层，我建议：

- child 入向量库
- parent 入 KV / 文档库
- 检索命中 child 后回溯 parent

这是最自然的落地方式。

---

## 30. 一个最实用的落地理解

如果把这份代码用一句话概括：

> 它不是单纯“把 PDF 转成文本”，而是把 PDF 转成 **适合知识库检索的层级化文本单元**。

也就是说，这份脚本真正做的事情有三层：

1. **调用 MinerU 完成版面解析与 OCR**
2. **把解析结果重组成页面级结构对象**
3. **把页面对象进一步切成适合 RAG 的 parent / child chunks**

这也是为什么它比“直接抽纯文本再按长度切块”的方案明显更适合生产环境。

---

## 31. 一个简化版伪代码流程

```python
raw_pages = load_pdf(pdf_path)
chunk_docs = texts_split(raw_pages, include_parents=False)
write_langchain_jsonl(chunk_docs, output_path)
```

更展开一点就是：

```python
# 1. 运行 MinerU
content_list = mineru_parse(pdf)

# 2. 按页整理
page_docs = build_page_documents(content_list)

# 3. 清洗文本
page_docs = clean_and_filter(page_docs)

# 4. 先做语义分组
semantic_groups = sentence_grouping(page_text)

# 5. 组合成 parent chunk
parents = merge_groups_by_token_limit(semantic_groups)

# 6. 再切 child chunk
children = recursive_split(parents)

# 7. 关联图表和公式
attach_visuals_and_equations(children)

# 8. 导出 JSONL
export(children)
```

---

## 32. 最后总结

你这套 `parse_mineru_v2_core.py` 的核心思路可以总结为：

### Parsing 层

- 用 MinerU / Magic-PDF 做 PDF 版面解析
- 借助 PaddleOCR 系列模型完成 OCR
- 输出 block 级结构化结果

### Structuring 层

- 按页重组 block
- 抽取正文、图、表、公式
- 清洗噪声、过滤参考文献
- 形成 page-level Document

### Chunking 层

- 先按句子做 semantic grouping
- 再合并成 parent chunk
- 再递归切成 child chunk
- 关联附近图表和公式
- 建立 parent-child 层级关系

### Export 层

- 输出 LangChain 可直接消费的 JSONL
- 当前默认只保留精简 metadata

因此，这不是简单的 OCR 脚本，而是一套 **面向 RAG / 检索系统的数据准备流水线**。

---

## 33. 我对你当前系统的直接判断

如果你接下来想把这套方案真正用于问答系统，我最建议先做两件事：

1. **保留更多 metadata 到 JSONL**
2. **让 chunk 边界更感知标题和图表结构**

只做这两步，整体效果通常就会明显提升。
