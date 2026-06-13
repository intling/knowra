# OCR 图片内容提取适配性分析

## 背景

当前 knowra 已完成文件上传、Docling 文档解析、解析产物落盘，以及解析后自动分块。现阶段解析结果主要保存为：

- `content.md`
- `content.txt`
- `docling.json`
- 数据库中的 `parsed_documents`、`document_segments`
- 数据库中的 `document_chunk_jobs`、`document_chunks`

本地目前不保存 PDF 页面图、图表图片、表格截图或其他派生图片资产。旧的 document-parsing OpenSpec 已把“不保存派生图片资产”定义为首版边界。

## 当前代码与契约观察

1. OCR 开关已经存在，但默认关闭。
   - `backend/app/core/config.py` 中已有 `document_parse_ocr_enabled: bool = False`。
   - `backend/.env.example` 中已有 `DOCUMENT_PARSE_OCR_ENABLED=false`。
   - `DoclingParserAdapter` 会把该开关传入 `PdfPipelineOptions.do_ocr`。

2. 当前解析持久化产物是文本和结构化 JSON，不是图片资产。
   - `ParsedArtifactStorage` 只写入 `content.md`、`content.txt`、`docling.json`。
   - `parsed_documents` 只保存这些产物的 storage key。

3. 当前分块链路是文本中心的。
   - `DocumentChunk` 保存 `text`、`contextualized_text`、`token_count`、`page_numbers`、`chunk_type`、`source_segment_indices`、`metadata_json`。
   - 分块输入来自同一次解析任务里的 transient `DoclingDocument`，不是从旧 `docling.json` 还原。

4. 当前 `document_segments` 仍偏粗粒度。
   - Docling 解析成功后，当前适配器主要把完整导出文本作为一个 `document` segment 保存。
   - 如果要让 OCR 内容具备稳定引用能力，仅有全文文本是不够的，最好能保留页码、结构引用、可能的 bbox 或 Docling self_ref 等来源信息。

5. 当前代码层面的 OCR 配置主要落在 PDF pipeline。
   - 对扫描版 PDF 的 OCR 支持路径比较自然。
   - 对 DOCX/PPTX 内嵌图片、截图、图表等是否能稳定 OCR，需要单独验证，不应直接假设等同支持。

## 结论

适合添加 OCR 提取图片内容能力，但建议先把目标收窄为“解析阶段可选地把图片中的文字提取为可检索文本”，暂时不要升级为“本地保存图片资产”。

更准确地说：

- 适合现在做：OCR 文本提取。
- 不建议现在做默认能力：保存页面图、图表图片、截图等图片文件。
- 可以预留后续能力：图片资产索引、视觉引用、多模态理解、图表摘要。

## 为什么适合做 OCR 文本提取

OCR 与 knowra 的核心价值非常贴合。knowra 的主线是“接入资料 -> 解析内容 -> 分块与索引 -> 用户提问 -> 检索相关片段 -> 生成带引用的回答”。如果课程资料、扫描 PDF、截图式讲义、实验报告扫描件里有大量文字，而 OCR 没有进入文本产物和 chunk，后续 embedding、语义检索、RAG 都会天然漏召回。

当前项目也已经有比较合适的接入点：

```text
uploaded_files
  -> document_parse_jobs
  -> DoclingParserAdapter
  -> content.md / content.txt / docling.json
  -> document_chunks
  -> 后续 embedding / 检索 / RAG
```

OCR 文本如果能在 `DoclingParserAdapter` 阶段进入 `DoclingDocument`，后续 Markdown、纯文本、Docling JSON、HybridChunker 分块都能自然消费它。这样符合现有架构，不需要先引入图片资产表或多模态检索。

## 为什么不建议现在保存图片资产

保存图片文件是另一类能力，复杂度明显更高：

- 存储成本会上升，尤其是 PDF 页面图、PPT 截图、图表图片可能远大于纯文本。
- 隐私暴露面变大，图片里可能包含手写内容、证件、课堂截图、个人信息。
- 当前没有图片资产表、图片 storage key、清理策略、权限 API、前端预览和引用定位契约。
- 当前 chunk 和后续检索设计还是文本中心，图片资产暂时没有明确消费方。
- 现有 OpenSpec 明确首版不保存派生图片资产，若改变该边界，应创建新的 OpenSpec 变更。

所以，把“OCR 出来的文字”作为文本知识进入解析和分块，是轻量且收益高的增强；把“图片本体”作为本地资产持久化，则应等待视觉引用或多模态检索需求明确后再做。

## 建议的能力边界

### 第一阶段：OCR 文本进入解析产物

目标：

- 支持扫描型 PDF 或图片型 PDF 中的文字进入 `content.txt`、`content.md`、`docling.json`。
- OCR 结果可被现有分块流程消费。
- 不保存页面图、截图、图表图片。
- 保留来源元数据，至少包括页码；如果 Docling 可提供，进一步保留 bbox/self_ref/元素类型。

验收关注：

- OCR 开启后，扫描 PDF 不再因为“无文本内容”解析失败。
- OCR 文本能进入 chunk。
- OCR 关闭时行为保持现状。
- OCR 失败时解析作业有可诊断错误，不能静默生成空知识。

### 第二阶段：图片级文本片段

目标：

- 为 OCR 结果建立更细的 segment 或 metadata 表达。
- 例如 segment_type 可区分 `ocr_text`、`image_text`、`figure_text`。
- chunk 的 `metadata_json` 能追溯到页码、图片或 Docling item 引用。

这一阶段仍可以不保存图片文件，只保存 OCR 文本和来源信息。

### 第三阶段：图片资产与视觉引用

只有当产品明确需要“引用时展示原图区域”、“查看截图来源”、“图表视觉问答”时，再考虑：

- 新增 `document_media_assets` 或类似模型。
- 保存图片 storage key、mime、hash、page_no、bbox、source_ref、extracted_text。
- 设计清理策略、权限 API、前端预览、引用展示。
- 评估多模态 embedding 或图片 captioning。

## 风险与约束

1. 解析耗时会增加。
   OCR 对 CPU、模型文件和页面数量更敏感。当前仍使用 FastAPI `BackgroundTasks`，还不是生产级独立 worker。大文件或批量 OCR 可能让后台任务变慢或中断后难恢复。

2. 模型与缓存要离线可用。
   项目已有 `DOCUMENT_PARSE_DOCLING_CACHE_DIR`，但 OCR 相关 artifacts 需要明确下载、缓存和启动检查策略。

3. 测试集不能默认依赖慢 OCR。
   当前测试设计刻意避免 OCR 和大文件进入默认测试集。新增 OCR 时，适合用小型 fixture 或 mock 验证主流程，再把真实 OCR 作为可选 smoke/integration。

4. 引用质量不能只靠全文。
   如果 OCR 文本只混入全文，后续回答能检索到，但引用可能只到文档或页级。若目标是可追溯问答，应尽早保留页码和元素级元数据。

5. DOCX/PPTX 内嵌图片 OCR 需要单独验证。
   当前代码明确配置的是 PDF OCR。PPT 截图、Word 内嵌图片、图表图片是否能稳定进入 Docling 文本输出，需要先做 spike。

## 推荐判断

建议添加，但不要把它做成“图片存储功能”。

更推荐的下一步是：在当前 `add-document-chunking-docling` 变更收尾后，单独创建一个 OpenSpec 变更，名称可以类似 `add-ocr-text-extraction`。该变更只承诺 OCR 文本进入解析产物和分块结果，不承诺保存图片本体。

如果只是本地验证扫描 PDF 效果，可以先在 `.env` 中打开：

```env
DOCUMENT_PARSE_OCR_ENABLED=true
```

然后用一份小型扫描 PDF 跑解析，比较开启前后的 `content.txt`、`docling.json` 和 `document_chunks`。如果 OCR 文本已经能稳定进入 chunk，首个正式变更可以很小；如果只能进入粗粒度全文，或者页码/图片来源不稳定，再把 segment 结构细化纳入变更范围。

