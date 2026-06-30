## Context

knowra 当前已经完成基础用户体系和单文件上传存储能力。上传后的原始文件会写入应用内存储，并通过 `uploaded_files.storage_key`、`owner_user_id`、`checksum_sha256` 和 `status` 保留可追溯元数据。下一步需要让这些原始资料进入“解析内容”阶段，为后续分块、索引、检索和带引用问答提供稳定输入。

本变更以 Docling 作为主要文档解析器，目标格式覆盖 PDF、DOCX、PPTX、TXT 和 Markdown。解析结果保存为三类文本/结构化产物：Markdown、纯文本和 Docling JSON。首版明确不保存 PDF 页面图、图表图片、表格截图等派生图片资产。

整体链路：

```text
uploaded_files
  -> POST /api/uploads/{upload_id}/parse
  -> document_parse_jobs(queued)
  -> BackgroundTasks.add_task(run_parse_job, job_id)
  -> run_parse_job 重新读取作业与上传记录
  -> DoclingParserAdapter 转换原始文件
  -> ParsedArtifactStorage 写 content.md/content.txt/docling.json
  -> parsed_documents + document_segments 入库
  -> document_parse_jobs(succeeded | failed)
```

## Goals / Non-Goals

**Goals:**

- 为当前用户已上传文件创建文档解析作业，并通过 API 查询状态。
- 使用 Docling 作为主要解析器，解析 PDF、DOCX、PPTX、Markdown，并为 TXT 提供同一输出契约下的规范化结果。
- 持久化解析作业、解析结果和粗粒度结构片段，支持后续 chunking、索引和引用定位。
- 保存 Markdown、纯文本和 Docling JSON 三类解析产物，数据库只保存 `storage_key` 和元数据。
- 使用 FastAPI `BackgroundTasks` 作为首版测试调度器，但让任务执行函数和调度器边界兼容未来独立 worker + 队列。
- 前端在上传成功后自动提交解析作业，并展示解析中、完成、失败和重试反馈。

**Non-Goals:**

- 不实现 embedding、pgvector 索引、语义检索、RAG 问答或最终引用生成。
- 不实现生产级独立 worker、Redis/RQ/Celery/Arq 队列部署。
- 不保存 PDF 页面图、图表图片、表格截图或其他派生图片资产。
- 不实现复杂 OCR 配置界面、图片/公式/表格可视化编辑。
- 不实现文档版本对比、增量解析、多文件批处理或对象存储迁移。

## Decisions

### Decision 1: 解析由上传记录触发，而不是上传 API 内同步执行

新增 `POST /api/uploads/{upload_id}/parse`。路由层校验当前用户和上传记录归属后创建 `document_parse_jobs`，返回 `202 Accepted`。上传 API 继续只负责原始文件保存。

选择理由：

- 上传和解析耗时、错误分支、依赖体积不同，拆开后更容易测试和重试。
- PDF/PPTX/OCR 可能耗时较长，不应阻塞上传响应。
- 解析结果可以按 `uploaded_file_id` 和 `source_checksum_sha256` 重建，后续可以支持重新解析。

替代方案：

- 上传后同步解析：用户路径短，但接口超时和失败补偿复杂，当前不采用。
- 前端直接上传到解析接口：会绕过稳定的上传存储边界，当前不采用。

### Decision 2: 首版使用 `BackgroundTasks`，但抽象 `ParseJobDispatcher`

首版新增一个测试版 dispatcher，将作业 ID 提交给 FastAPI `BackgroundTasks`：

```text
BackgroundTasksParseJobDispatcher.enqueue(job_id)
  -> background_tasks.add_task(run_parse_job, job_id)
```

真正的解析逻辑放在 `run_parse_job(job_id)` 或同等任务函数中。任务函数必须从数据库重新读取作业和上传记录，不依赖请求上下文中的 ORM 对象。

选择理由：

- `BackgroundTasks` 能快速验证上传后解析闭环，减少首版基础设施成本。
- 持久化作业表是状态事实源，避免把任务状态只放在内存。
- dispatcher 边界让后续替换为 `QueueParseJobDispatcher` 时不改变 API 和数据模型。

替代方案：

- 立即引入独立 worker + 队列：更可靠，但需要额外依赖和部署约束，会扩大首版范围。
- 同步执行解析：实现最少，但不适合大文件和 OCR。

### Decision 3: 解析产物只保存 Markdown、纯文本和 Docling JSON

解析产物保存到独立目录，例如：

```text
storage/parsed/{owner_user_id}/{uploaded_file_id}/{parse_job_id}/content.md
storage/parsed/{owner_user_id}/{uploaded_file_id}/{parse_job_id}/content.txt
storage/parsed/{owner_user_id}/{uploaded_file_id}/{parse_job_id}/docling.json
```

数据库保存 `markdown_storage_key`、`text_storage_key`、`docling_json_storage_key`、文档级元数据和 checksum 信息。

选择理由：

- Docling JSON 是后续重新分块、抽取结构、引用定位的事实中间表示。
- Markdown 适合人工预览和解析质量检查。
- 纯文本适合快速预览、兜底分块和轻量全文处理。
- 不保存派生图片可以降低本地存储膨胀、隐私暴露面和清理复杂度。

替代方案：

- 只保存 Docling JSON：结构完整，但前端预览和调试成本高。
- 保存页面图和图表图片：有利于可视化引用，但本地存储成本和隐私面过大，当前不采用。
- 把文本直接写入数据库大字段：查询简单，但会让数据库膨胀，当前不采用。

### Decision 4: 数据模型分为作业、文档结果和结构片段

新增模型建议：

- `DocumentParseJob`
  - `id`
  - `uploaded_file_id`
  - `owner_user_id`
  - `status`: `queued`、`running`、`succeeded`、`failed`、`cancelled`
  - `parser_name`
  - `parser_version`
  - `attempt_count`
  - `started_at`
  - `finished_at`
  - `error_code`
  - `error_message`
  - `created_at`
  - `updated_at`
- `ParsedDocument`
  - `id`
  - `uploaded_file_id`
  - `parse_job_id`
  - `owner_user_id`
  - `source_checksum_sha256`
  - `markdown_storage_key`
  - `text_storage_key`
  - `docling_json_storage_key`
  - `title`
  - `page_count`
  - `metadata_json`
  - `created_at`
- `DocumentSegment`
  - `id`
  - `parsed_document_id`
  - `owner_user_id`
  - `sequence_index`
  - `segment_type`
  - `page_no`
  - `heading_path`
  - `text`
  - `metadata_json`
  - `created_at`

索引建议：

- `document_parse_jobs.owner_user_id`
- `document_parse_jobs.uploaded_file_id`
- `document_parse_jobs.status`
- `parsed_documents.uploaded_file_id`
- `parsed_documents.parse_job_id`
- `document_segments.parsed_document_id`
- `document_segments.owner_user_id`
- `document_segments.sequence_index`

选择理由：

- 作业表表达异步生命周期。
- 解析结果表表达一次成功解析的可重建产物。
- 结构片段表为后续 chunking、引用定位和文档预览提供中间层，但不提前承诺 embedding chunk。

### Decision 5: Docling SDK 只出现在解析适配器内

新增 `DoclingParserAdapter` 或同等模块，封装 `DocumentConverter`、格式映射、PDF 选项、最大文件大小、最大页数、OCR 开关和异常转换。服务层只依赖项目内的 `ParsedDocumentPayload` 之类结构。

选择理由：

- 避免第三方 SDK 类型扩散到路由、数据库模型和前端 schema。
- 便于测试时 mock 解析器。
- 便于后续替换解析器或增加 fallback parser。

TXT 处理策略：

- 优先在实现 spike 中确认当前 Docling 版本是否支持 plain text 输入。
- 若版本不提供稳定 TXT 输入格式，则在同一 parser facade 下读取文本并生成同样的 Markdown、Text、JSON-like 结构化产物。
- 外部契约仍然表现为 `document-parsing` 能处理 TXT。

### Decision 6: API 响应面保持状态驱动

首版 API：

- `POST /api/uploads/{upload_id}/parse`
  - 成功创建作业返回 `202`
  - 非当前用户文件返回 `404` 或 `403`
  - 不支持格式返回 `415`
  - 已有运行中作业返回 `409`，响应体包含已有运行中作业信息和上传文档信息
- `GET /api/document-parse-jobs/{job_id}`
  - 返回当前用户作业状态、错误、时间戳、关联上传 ID
- `GET /api/uploads/{upload_id}/parsed-document`
  - 返回最新成功解析结果元数据和产物引用
- `GET /api/parsed-documents/{id}/segments`
  - 分页返回结构片段

选择理由：

- 前端可以用同一状态模型展示等待、运行、成功、失败。
- 后续替换 dispatcher 不影响 API。
- 解析结果预览与作业状态解耦。

### Decision 7: 上传白名单与解析格式策略分离

本变更不强制扩展 `ALLOWED_UPLOAD_CONTENT_TYPES` 的默认值。上传层继续只负责“哪些原始文件可以进入系统”，并通过既有配置显式管理；解析层新增独立格式策略，例如：

- `DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES`
- `DOCUMENT_PARSE_ALLOWED_EXTENSIONS`

解析 API 在创建作业前执行轻量服务端识别，不只相信客户端上传时记录的 MIME：

- PDF：检查 MIME/扩展名，并抽样检查文件头是否为 `%PDF-`。
- DOCX/PPTX：检查 MIME/扩展名，并验证文件为 ZIP 容器且包含 OOXML 关键条目，例如 `[Content_Types].xml`、`word/document.xml` 或 `ppt/presentation.xml`。
- TXT/Markdown：检查 MIME/扩展名，并验证文件可按配置编码读取或在采样范围内是可接受文本。
- 所有格式：继续受最大解析字节数、最大页数和上传归属校验约束；默认最大解析字节数为 `50 * 1024 * 1024`，默认最大页数为 `100`。

这个识别过程只需要读取少量文件头、ZIP 中央目录或有限文本采样，性能成本低；真正耗时的 Docling 转换只在格式策略通过后执行。

选择理由：

- 上传默认白名单保持保守，避免因为新增解析能力而扩大默认接入面。
- 解析入口即使面对已上传文件，也会再次执行格式策略校验，形成第二道门。
- 部署环境如果希望支持 PPTX 等格式，可以显式配置上传允许类型和解析允许类型，而不是由代码默认放开。
- 前端可以展示产品支持的解析格式，但上传失败和解析拒绝都以服务端实际配置为准。

替代方案：

- 默认上传白名单覆盖全部解析目标格式：路径短，但会扩大默认上传面，当前不采用。
- 只依赖客户端 MIME：性能最好但不安全，当前不采用。
- 对所有文件做完整内容解析后再判断类型：准确但成本高，当前不采用。

## Risks / Trade-offs

- Docling 依赖体积和安装时间增加 → 锁定版本，记录 Python 3.14 兼容性；必要时先用小型 fixture 做 smoke test。
- PDF OCR 消耗 CPU 且耗时不可控 → 首版默认关闭 OCR，并通过配置开关控制。
- `BackgroundTasks` 不具备生产级可靠性 → 只作为测试版调度器；作业状态持久化；任务函数幂等；后续替换为独立 worker + 队列。
- 进程中断导致作业停留在 `running` → 增加 stuck job 处理策略，例如启动时或定时把超时 `running` 标记为 `failed` 或重新入队。
- 不保存派生图片会降低视觉引用能力 → 首版引用定位落在文件、页码、标题路径、段落序号和 Docling 结构引用上；可视化引用后续单独设计。
- Docling 输出结构可能随版本变化 → 保存原始 Docling JSON，同时把 knowra 需要的字段规范化到自有表。
- 大文件或损坏文件导致失败 → 设置解析最大字节数、最大页数、错误码和可重试状态。
- TXT 支持存在版本差异 → 在 parser facade 内兜底，保持外部输出契约一致。

## Migration Plan

1. 增加 Docling 依赖和必要配置，更新后端锁文件与 `.env.example`。
2. 增加解析允许内容类型和扩展名配置；上传允许内容类型保持显式配置管理，部署需要 PPTX 等格式时再按环境放开。
3. 新增解析相关 SQLModel 模型和 Alembic migration，并确保 downgrade 删除解析表。
4. 新增解析 schema、服务、Docling 适配器、解析产物存储和 BackgroundTasks dispatcher。
5. 新增解析 API 路由并注册到后端 API router。
6. 新增前端解析 API 封装和上传成功后的自动解析状态 UI。
7. 更新 README 和端侧文档，说明解析配置、产物目录、BackgroundTasks 限制和验证命令。
8. 回滚时移除前端解析入口、后端解析路由/服务、Docling 依赖和解析配置，通过 Alembic downgrade 删除解析表；`storage/parsed` 下已有文本/JSON 产物按目录清理策略单独处理。

## Open Questions

- 当前锁定 Docling 版本对 Python 3.14 和 TXT 输入的支持细节需要在实现前用 fixture spike 确认。
- 运行中重复触发解析时，API 固定返回 `409`，并在响应中提供已有运行中作业和上传文档信息。
- `DocumentSegment.text` 是否直接入库，以及单条片段最大长度限制，需要在实现时结合 PostgreSQL 存储和后续 chunking 策略细化。
- 前端是否需要新增“服务端支持格式配置查询”接口，以避免 UI 固定展示当前部署未放开的格式，需要在前端红测试前确认。
