## Context

knowra 当前已经完成基础用户、上传存储和文档解析能力。解析流程会从 `uploaded_files` 创建 `document_parse_jobs`，通过 `BackgroundTasksParseJobDispatcher` 进入 `run_parse_job(job_id)`，读取原始上传文件，调用 Docling 解析适配器，写入 Markdown、纯文本和 Docling JSON 产物，并持久化 `parsed_documents` 与 `document_segments`。

本变更承接核心链路中的下一步：

```text
uploaded_files
  -> document_parse_jobs
  -> DoclingParserAdapter
  -> parsed_documents + document_segments
  -> document_chunk_jobs
  -> DoclingChunkerAdapter(HybridChunker)
  -> document_chunks
  -> 后续 embedding / 检索 / RAG
```

关键约束是：分块输入必须是解析运行中内存里的 `DoclingDocument`，不是已经写入文件的 `docling.json`。`docling.json` 继续作为调试、审计和后续分析产物存在，但不作为首次分块或重新分块的文档对象还原来源。

## Goals / Non-Goals

**Goals:**

- 在解析后台任务成功后自动执行文档分块，并持久化分块作业状态。
- 调整解析适配器内部输出，使同一次任务中可以拿到 transient `DoclingDocument`。
- 使用 Docling `HybridChunker` 生成 token 感知、保留结构元数据的 chunk。
- 为每个 chunk 持久化原始文本、contextualized 文本、token 计数、标题路径、页码、来源元数据和可选来源 segment 索引。
- 通过分块 API 支持作业状态查询、chunk 分页查询、chunk 详情查询和参数变更后的重新分块。
- 保持 `document_segments` 作为解析阶段产物，不因分块被修改或合并。
- 保留未来替换为独立 worker + 队列、embedding、检索和 RAG 的服务边界。

**Non-Goals:**

- 不实现 embedding、pgvector chunk 索引、语义检索、RAG 问答或引用生成。
- 不提供独立的首次 `POST /chunk` API；首次分块始终由解析成功路径自动触发。
- 不从 `docling.json`、pickle 或已落地解析产物还原 `DoclingDocument` 后执行分块。
- 不实现多分块策略切换、用户自定义 chunker、跨解析运行的旧 segment 强对齐算法。
- 不引入生产级独立 worker、队列、取消任务或清理旧 chunk 文件的管理界面。

## Decisions

### Decision 1: 解析成功后在同一后台任务内自动分块

`run_parse_job(job_id)` 在 Docling 解析、解析产物写入、`parsed_documents` 和 `document_segments` 持久化成功后，继续在同一任务上下文中调用 `DocumentChunkingService`。分块服务创建 `document_chunk_jobs`，将状态从 `running` 写到 `succeeded` 或 `failed`。

选择理由：

- 解析运行仍持有内存中的 `DoclingDocument`，可以直接传给分块适配器。
- 避免 pickle/JSON 序列化与还原带来的版本兼容和可靠性风险。
- 与现有 `BackgroundTasks` 解析调度一致，首版不额外引入队列基础设施。

替代方案：

- 独立 `POST /chunk` 从持久化解析产物启动：会迫使系统从 `docling.json` 还原文档对象，当前不采用。
- 立即引入独立 worker + 队列：生产可靠性更好，但会扩大首版范围，当前只保留服务边界。

### Decision 2: 解析内部结果携带 transient `DoclingDocument`

解析适配器输出应区分可持久化 payload 和 transient runtime 对象。建议在现有 `ParsedDocumentPayload` 外新增或扩展内部结果结构：

```text
ParsedDocumentResult
  persistent_payload: ParsedDocumentPayload
  transient_docling_document: Any | None
```

`transient_docling_document` 只允许在当前后台任务内传递给 `DoclingChunkerAdapter`。它不得写入数据库、文件存储、API schema、日志详情或前端响应。

选择理由：

- 服务层不用直接依赖 Docling SDK 类型。
- 可以用测试明确证明持久化内容不包含第三方运行时对象。
- 当 TXT 兜底或某些解析器不提供 DoclingDocument 时，系统可以创建失败的分块作业并记录清晰错误，而不是静默回退到文件还原。

替代方案：

- 把 DoclingDocument 放进可持久化 payload：会污染 API/schema 和存储边界，当前不采用。
- 在分块服务中读取 `docling.json` 还原：与核心约束冲突，当前不采用。

### Decision 3: 用 `DoclingChunkerAdapter` 封装 HybridChunker

新增 `backend/app/services/document_chunker.py` 或同等模块，封装 Docling `HybridChunker`、HuggingFace tokenizer、`contextualize()`、异常转换和输出规范化。服务层只消费项目内的 chunk 结果结构，不在适配器外暴露 Docling chunk 或 SDK 内部类型。

默认配置：

- `DOCUMENT_CHUNKING_ENABLED=true`
- `DOCUMENT_CHUNK_MAX_TOKENS=512`
- `DOCUMENT_CHUNK_TOKENIZER_MODEL=Qwen/Qwen2-7B`
- `DOCUMENT_CHUNK_MERGE_PEERS=true`
- `DOCUMENT_CHUNK_REPEAT_TABLE_HEADER=true`
- `DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES=2048`
- `DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR=storage/chunks`

选择理由：

- `HybridChunker` 同时保留文档结构边界并控制 token 长度，适合后续 embedding。
- Qwen2 tokenizer 对中文资料更友好，也能为后续中文知识库检索保持 token 计数一致性。
- 适配器边界让测试可以 mock chunker，不把真实 tokenizer 下载变成默认单元测试前置条件。

替代方案：

- 使用 `HierarchicalChunker`：结构保留好，但不能控制 token 长度，当前不适合作为 embedding 前置。
- 先导出 Markdown 再手写切块：实现可控但会丢失 Docling 结构元数据，当前不采用。

### Decision 4: 分块作业和分块结果分表存储

新增 `DocumentChunkJob`：

- `id`
- `parsed_document_id`
- `owner_user_id`
- `status`: `queued`、`running`、`succeeded`、`failed`、`superseded`
- `chunker_name`
- `chunker_version`
- `chunk_config_json`
- `chunk_count`
- `attempt_count`
- `started_at`
- `finished_at`
- `error_code`
- `error_message`
- `created_at`
- `updated_at`

新增 `DocumentChunk`：

- `id`
- `chunk_job_id`
- `parsed_document_id`
- `owner_user_id`
- `sequence_index`
- `text`
- `text_storage_key`
- `contextualized_text`
- `contextualized_text_storage_key`
- `token_count`
- `heading_path`
- `page_numbers`
- `chunk_type`
- `source_segment_indices`
- `metadata_json`
- `created_at`

索引建议：

- `document_chunk_jobs.owner_user_id`
- `document_chunk_jobs.parsed_document_id`
- `document_chunk_jobs.status`
- `document_chunks.chunk_job_id`
- `document_chunks.parsed_document_id`
- `document_chunks.owner_user_id`
- `document_chunks(parsed_document_id, sequence_index)`

选择理由：

- 作业表表达生命周期、错误和配置快照。
- 结果表表达可分页、可追溯、可供后续 embedding 消费的 chunk。
- `document_segments` 与 `document_chunks` 生命周期和粒度不同，不复用同一张表。

### Decision 5: Chunk 文本采用阈值混合存储

`text` 和 `contextualized_text` 各自按 UTF-8 字节数判断。内容 `<= DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES` 时直接入库；超过阈值时写入 `storage/chunks/{owner_user_id}/{parsed_document_id}/{chunk_job_id}/` 下的文件，并在对应 `*_storage_key` 字段保存引用。

选择理由：

- 大多数 chunk 可以直接查询并预览，前端体验简单。
- 长表格或长段落不会让数据库大字段无限膨胀。
- 与解析产物只保存 storage key 的策略一致，便于后续清理。

替代方案：

- 全部入库：开发简单，但大文档和重分块会带来数据库膨胀。
- 全部走文件：数据库轻，但分页预览和后续 embedding 读取成本更高。

### Decision 6: 重新分块触发重新解析原始文件

`POST /api/parsed-documents/{parsed_document_id}/rechunk` 校验归属后，按请求参数创建新的分块作业，并重新读取原始上传文件执行解析，以获得新的内存 `DoclingDocument`，随后使用新参数分块。该流程不得读取旧 `docling.json` 作为分块输入。

如果同一解析结果存在 `queued` 或 `running` 的分块作业，API 返回 `409`。重新分块采用“成功后切换活跃结果”的策略：新作业处于 `queued` 或 `running` 时，旧的成功分块作业仍保持活跃，默认 chunk 查询继续返回旧结果；新作业失败时，旧结果继续保持活跃且不被标记为 `superseded`；只有新作业成功持久化完整 chunk 集合后，系统才将旧的活跃分块作业标记为 `superseded`，并让默认查询切换到新结果。若原始上传文件已删除或不可读，API 返回非 2xx，并且不创建不可执行的分块作业。

选择理由：

- 参数变更需要新 chunk 集合，但旧内存对象已经不可用。
- 重新解析是避免不可靠还原的明确代价。
- 新作业成功后再切换，可以让用户在重分块耗时或失败时继续使用旧 chunk 结果，避免知识库从可预览状态退回空状态。
- 保留旧结果可以支持回溯和对比。

替代方案：

- 从旧 `docling.json` 还原再重分块：实现看似便宜，但风险正是本方案要规避的点。
- 重分块时同步阻塞 API：接口超时风险高，当前不采用。

### Decision 7: API 和前端保持状态驱动

首版 API：

- `GET /api/document-chunk-jobs/{job_id}`：查询当前用户分块作业状态、配置快照、错误和 chunk 数。
- `GET /api/parsed-documents/{parsed_document_id}/chunks`：分页读取最新活跃分块作业的 chunk。
- `GET /api/document-chunks/{chunk_id}`：读取当前用户单个 chunk 详情。
- `POST /api/parsed-documents/{parsed_document_id}/rechunk`：使用新参数重新解析原始文件并分块。

前端在上传解析链路中展示：

- 解析成功且分块运行中：显示分块中。
- 分块成功：显示分块完成和 chunk 预览入口。
- 分块失败：显示可理解错误和重新分块入口。
- 重新分块运行中：禁用重复触发。

选择理由：

- 用户能理解“解析完成”和“分块完成”是两个相邻但不同的阶段。
- API 不承诺后续检索或问答已经可用。
- 与现有解析状态 UI 和 API client 风格一致。

## Risks / Trade-offs

- Docling `HybridChunker` 或 tokenizer 依赖在当前锁文件中不可用 → 实现前用 spike 和小 fixture 验证导入路径、tokenizer 下载和缓存目录；必要时更新依赖并记录。
- 分块失败会让解析成功但 chunk 不可用 → 分块状态独立持久化，前端展示明确错误；用户通过 `/rechunk` 触发完整重试。
- `BackgroundTasks` 进程中断可能留下 `running` 分块作业 → 沿用解析作业的 stuck job 处理策略，后续队列化时统一改造。
- 重新分块需要重新解析原始文件，耗时和资源成本高 → 明确这是避免不可靠还原的 trade-off；通过最大文件大小、页数和错误码控制风险。
- 旧 chunk 结果保留会增加存储占用 → 首版不主动删除，后续可增加清理 API 或运维命令。
- `source_segment_indices` 可能无法可靠映射 → 允许为空，不做跨解析运行强对齐；依赖页码、标题路径和 Docling metadata 辅助追溯。
- 前端展示 chunk 可能让用户误以为已经完成检索 → UI 文案只表达“分块完成/可预览”，不表达“可问答”或“已索引”。

## Migration Plan

1. 增加分块配置到 `backend/app/core/config.py` 和 `backend/.env.example`。
2. 如 spike 发现依赖不足，增加 tokenizer/chunking 相关依赖并更新 `uv.lock`。
3. 新增 `DocumentChunkJob`、`DocumentChunk` SQLModel，并确保 Alembic metadata 可发现。
4. 新增 Alembic migration 创建 `document_chunk_jobs` 和 `document_chunks` 表、外键与索引，downgrade 删除新增表。
5. 调整解析适配器内部输出契约，携带 transient `DoclingDocument`，并证明该对象不会进入持久化 payload。
6. 新增 chunker adapter、chunk artifact storage、chunking service 和 API schema。
7. 在 `run_parse_job` 成功路径接入自动分块。
8. 新增分块 API 路由并注册到后端 router。
9. 新增前端 API client、状态展示、chunk 预览和重新分块入口。
10. 更新根 README、后端 README、前端 README 和环境变量模板。
11. 回滚时移除前端入口、后端路由/服务、配置和依赖；执行 Alembic downgrade 删除分块表；按 `storage/chunks` 目录清理策略删除文件产物。

## Open Questions

- 当前 Docling 版本中 `HybridChunker` 的推荐导入路径和 tokenizer extra 是否已由现有依赖满足，需要 spike 确认。
- 前端是否需要单独页面展示 chunk 详情，还是在首页/文件详情中以内联抽屉展示，需结合当前信息架构确定。
