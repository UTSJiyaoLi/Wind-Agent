# MinerU 文档解析与分块流程说明

## 项目概述

该项目基于 MinerU 构建了一套完整的文档解析（parsing）与文本分块（chunking）流程。系统主要用于将 PDF 等复杂文档转换为结构化数据，并进一步切分为适用于下游检索或大模型处理的文本块。

---

## 一、整体流程

该系统的处理流程如下：

1. 输入 PDF 文档
2. 调用 MinerU / PDF-Extract-Kit 进行解析
3. 生成结构化中间结果（content_list.json）
4. 进行页面级结构重建
5. 文本清洗与噪声过滤
6. 构建父子块（parent-child chunking）
7. 关联图像、表格与公式
8. 输出标准 JSONL 数据

---

## 二、Parsing（解析阶段）

在解析阶段，系统调用 MinerU 或 magic-pdf 工具完成：

- 版面分析（layout detection）
- 文本块提取
- 表格与图片识别
- 阅读顺序恢复

输出结果通常为：

- content_list.json（核心结构数据）

该阶段的核心目标是将 PDF 转换为“结构化文档对象”。

---

## 三、结构重建（Structuring）

解析结果会进一步被处理为页面级结构：

- 按 page_id 分组
- 按阅读顺序排序 block
- 区分不同类型：
  - text
  - title
  - table
  - image

形成统一的数据结构，便于后续处理。

---

## 四、文本清洗（Cleaning）

系统会对解析出的文本进行标准化处理，包括：

- 去除多余空格与换行
- 合并断裂文本
- 过滤无效字符
- 去除页眉页脚噪声

该阶段提升文本质量，避免污染后续 embedding。

---

## 五、Chunking（分块策略）

系统采用分层 chunking 设计：

### 1. Parent Chunk

- 通常为段落级或章节级
- 保持语义完整性
- 用于高层检索

### 2. Child Chunk

- 从 parent 中进一步切分
- 控制 token 长度
- 用于精细匹配

### 3. 切分策略

- 按字符数或 token 数切分
- 保持句子完整性
- 支持重叠（overlap）

---

## 六、多模态信息处理

系统会对以下元素进行特殊处理：

- 表格：保留结构或转文本
- 图片：记录位置与引用
- 公式：单独标记

并与文本 chunk 建立关联关系。

---

## 七、输出格式

最终输出为 JSONL，每一行代表一个 chunk：

包含字段：

- text
- chunk_id
- parent_id
- page_id
- type（text/table/image）
- metadata

---

## 八、特点总结

该系统具有以下特点：

- 基于 MinerU 的高质量解析能力
- 分层 chunking 设计（适合 RAG）
- 支持多模态信息融合
- 输出结构清晰，便于下游使用

---

## 九、应用场景

- RAG 检索增强生成
- 文档问答系统
- 知识库构建
- 企业文档解析
