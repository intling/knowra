## Context

knowra 当前已通过 `uploaded_files` 保存原始上传文件及元数据，但这些文件尚未进入“解析内容 -> 分块与索引”的知识库主链路。后续 embedding、检索、RAG 和引用展示需要稳定的中间数据：文档级记录和可追溯 chunk。

本变更跨越后端数据模型、文件读取、解析器、BPE 分块、API 契约和前端资料列表状态。它不直接实现检索或生成，但会定义后续检索/RAG 可依赖的数据边界。

数据流：

```text
uploaded_files(status=stored)
        |
        v
LocalFileStorage.open(storage_key)
        |
        v
ParserRegistry -> ParsedDocument(text, metadata, source_map)
        |
        v
BpeChunker -> DocumentChunkDraft[]
        |
        v
documents + document_chunks
        |
        v
future: chunk_embeddings -> retrieval -> RAG citations
```

## Goals / Non-Goals

**Goals:**

- 从当前用户已上传的原始文件创建 `documents` 和 `document_chunks`。
- 首批支持 TXT、Markdown、PDF、DOCX、PPT/PPTX 的文本解析。
- PDF 首批只支持具备文本层的内容；无法抽取文本时生成 `failed` 文档。
- 用 BPE tokenizer 控制 chunk 大小和重叠窗口，并持久化 token 统计与 tokenizer 版本。
- 为每个 chunk 保存用户归属、文档归属、顺序、内容 hash、字符范围和 source locator。
- 通过 `/api/documents` API 暴露创建、列表、详情和 chunks 查询。
- 重复处理同一 `uploaded_file_id` 时返回 `409 Conflict`，响应体包含已有文档元数据。
- 让前端资料列表展示 `parsed` 和 `failed` 文档，failed 文档展示失败原因但不进入检索消费。

**Non-Goals:**

- 不实现 embedding、pgvector 写入、检索、重排或 RAG。
- 不实现 OCR、图片解析、PDF 复杂版面重建、复杂表格恢复、幻灯片视觉布局恢复或多模态理解。
- 不引入后台任务队列；首批处理请求保持同步语义。
- 不允许客户端指定文档归属、原始文件路径、parser、chunker 或 tokenizer。

## Decisions

### 1. 文档处理消费 `uploaded_files`，不重新上传

文档创建 API 只接收 `uploaded_file_id`。后端通过当前用户上下文查询 `uploaded_files`，要求记录属于当前用户且 `status = stored`，再通过 `storage_key` 读取原始文件。

替代方案是让客户端在文档处理接口再次上传文件。该方案会复制上传逻辑、削弱来源追溯，并让文件归属与存储一致性更难验证，因此不采用。

### 2. 新增 `documents` 与 `document_chunks` 两层模型

`documents` 表示“系统已处理或尝试处理过的资料”，保存上传文件关联、状态、parser/chunker/tokenizer 版本、chunk 数量、总字符数、内容 hash 和失败原因。`document_chunks` 表示检索和引用的最小稳定单元，保存内容、顺序、字符范围、token 数和 source locator。

替代方案是直接在 `uploaded_files` 上增加解析字段和 chunk JSON。该方案会混淆“已上传”和“已解析”状态，也不利于后续 embedding 表、检索评测和引用展示扩展，因此不采用。

### 3. Parser Registry + 专用解析器

后端新增 parser registry，根据 `content_type` 和文件扩展名选择解析器。首批解析器覆盖：

- TXT：按 UTF-8 文本读取，解码失败显式失败。
- Markdown：保留文本并提取标题路径。
- PDF：逐页抽取文本，source locator 至少包含页码。
- DOCX：抽取标题、段落和表格文本，source locator 至少包含段落序号或结构路径。
- PPT/PPTX：按幻灯片顺序抽取标题、文本框和备注，source locator 至少包含 slide index。

解析器必须输出统一的 `ParsedDocument(text, metadata, source_map)`。不支持类型或无法抽取有效文本时，不生成 `parsed` 文档。

替代方案是把不同文件类型的处理写在文档服务内部。该方案会让服务层承担过多格式细节，后续替换解析库或增加 OCR 时改动面更大，因此不采用。

### 4. BPE tokenizer 通过适配器接入

分块器依赖 `Tokenizer` 适配器，而不是直接依赖某个具体第三方库。适配器提供编码、计数和窗口切分能力，并向文档记录写入 `tokenizer_name`、`tokenizer_version` 和分块参数。具体依赖在实现阶段通过 TDD 和兼容性验证选择，但必须支持确定性 BPE token 计数。

替代方案是按字符数近似分块。该方案实现简单，但无法为后续模型上下文预算提供稳定依据，且用户已明确要求首批引入 BPE，因此不采用。

### 5. 同步处理，事务内保证成功文档与 chunks 一致

首批 `POST /api/documents` 在请求内完成读取、解析、分块和入库。成功时同一事务写入 `documents.status = parsed` 与完整 chunks，并保证 `chunk_count` 与实际 chunk 数一致。失败时记录或返回 `failed` 文档元数据，但不得留下 `parsed` 且 chunks 不完整的状态。

替代方案是引入后台任务队列。该方案更适合大文件和重试，但会额外引入任务状态、轮询、取消、重试和并发控制，本变更先不纳入。

### 6. 重复处理返回 `409 Conflict`

`uploaded_file_id` 在 `documents` 中保持唯一。若同一上传文件已有文档记录，再次创建时返回 `409 Conflict`，响应体包含已有文档元数据。这样前端可以展示已有结果，后端也避免重复 chunks 污染后续索引。

替代方案是幂等返回已有文档的 `200` 或 `201`。该方案会模糊“创建”和“读取已有结果”的语义，不利于前端明确反馈重复操作，因此不采用。

### 7. failed 文档是用户可见资料状态

解析失败、文本为空、原始文件缺失或不支持类型时，需要生成或保留 `failed` 文档元数据，并在资料列表中展示失败原因。`failed` 文档不得出现在 chunk 查询结果中，也不得被后续 embedding、检索或 RAG 消费。

替代方案是只返回 API 错误而不持久化失败记录。该方案会让用户在资料列表中看不到失败历史，也不利于排查，因此不采用。

## Risks / Trade-offs

- [Risk] PDF、DOCX、PPT/PPTX 解析库对 Python 3.14.5 的兼容性或文本质量不稳定。→ Mitigation：通过适配器隔离依赖；实现前用最小样例文件写失败测试；依赖选择和锁文件更新作为独立任务。
- [Risk] 同步处理大文件可能导致请求耗时较长。→ Mitigation：沿用上传大小限制；首批记录清晰错误；后续如需要再以独立 OpenSpec 设计异步任务队列。
- [Risk] BPE tokenizer 版本变化会导致 chunk 边界变化。→ Mitigation：持久化 tokenizer 名称、版本和参数；版本变化视为新一轮处理结果。
- [Risk] failed 文档进入资料列表可能被误认为可检索。→ Mitigation：前端明确展示失败状态；后端 chunk 查询和后续索引消费只允许 `parsed` 文档。
- [Risk] 解析器 source locator 粒度不一致。→ Mitigation：定义每类 parser 的最低定位要求，并把额外定位信息放入 JSON 扩展字段。

## Migration Plan

1. 新增 `documents` 与 `document_chunks` 模型和 Alembic migration。
2. 增加唯一约束：一个 `uploaded_file_id` 只能关联一个当前文档记录。
3. 增加常用索引：`owner_user_id`、`uploaded_file_id`、`status`、`created_at`、`document_id + chunk_index`。
4. 更新上传允许内容类型默认配置和 `.env.example`，覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX。
5. 部署前运行迁移；回滚时通过 Alembic downgrade 删除新增文档处理表。原始上传文件不随 downgrade 删除。

## Open Questions

- 具体选择哪一个 PDF、DOCX、PPT/PPTX 解析库和 BPE tokenizer 依赖，需要在实现任务中通过 Python 3.14.5 兼容性验证确定。
- 首批是否需要限制文档解析后的最大字符数或最大 chunk 数，可以在实现阶段结合上传大小限制和测试样例确定。
