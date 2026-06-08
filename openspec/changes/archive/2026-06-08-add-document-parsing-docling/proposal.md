## Why

knowra 已经具备用户文件上传与应用内原始文件存储能力，但资料还不能被解析为后续分块、索引、检索和引用生成可消费的结构化内容。现在需要补上核心工作流中的“解析内容”阶段，让用户上传的 PDF、DOCX、PPTX、TXT 和 Markdown 能进入可预览、可追溯、可重建的文档中间表示。

## What Changes

- 新增文档解析能力，允许当前用户为自己的已上传文件创建解析作业。
- 新增基于 Docling 的解析适配器，主要处理 PDF、DOCX、PPTX、Markdown，并为 TXT 提供同一输出契约下的规范化处理。
- 新增解析作业状态模型和 API，例如 `POST /api/uploads/{upload_id}/parse` 与 `GET /api/document-parse-jobs/{job_id}`。
- 新增解析结果持久化模型，保存 Markdown、纯文本、Docling JSON、文档级元数据和粗粒度结构片段。
- 新增解析产物存储目录和配置项，数据库仅保存稳定 `storage_key`，不直接保存大文本或 JSON 内容。
- 明确首版不保存 PDF 页面图、图表图片、表格截图或其他派生图片资产。
- 首版使用 FastAPI `BackgroundTasks` 作为测试版异步调度器，并通过调度器边界保留后续替换为独立 worker + 队列的空间。
- 不强制扩展上传默认允许内容类型；解析入口使用独立格式策略校验，PPTX 等格式是否允许上传由部署配置显式开启。
- 前端在上传成功后自动提交解析作业，展示解析中反馈、完成反馈和失败重试入口。
- 不实现 embedding、pgvector 索引、语义检索、RAG 问答、引用生成、生产级队列部署、文档版本对比或派生图片资产管理。

## Capabilities

### New Capabilities

- `document-parsing`: 定义当前用户已上传文件的解析作业、Docling 解析适配、解析结果产物、结构片段、API 契约、状态反馈和错误语义。

### Modified Capabilities

- 无。`file-upload-storage` 的默认上传白名单不在本变更中强制变更；解析目标格式由 `document-parsing` 的独立格式策略校验，上传层继续通过既有配置显式放开具体 MIME 类型。

## Impact

- 后端 API：新增文档解析相关路由，所有接口挂载在现有 `/api` 前缀下，并校验上传文件归属当前用户。
- 后端服务：新增解析编排服务、Docling 适配器、解析产物存储服务和 `BackgroundTasks` dispatcher；解析任务函数需要与未来队列 worker 解耦。
- 数据库：新增解析作业、解析结果和结构片段相关表及 Alembic migration。
- 后端依赖：新增 Docling 及其运行依赖；需要确认 Python 3.14、OCR 配置、模型缓存和安装体积影响。
- 后端配置：新增解析开关、解析产物目录、最大解析字节数、最大页数、OCR 开关、Docling 运行缓存目录、调度器类型、解析允许内容类型和解析允许扩展名；上传允许内容类型仍由上传配置显式管理。
- 前端：新增解析 API 封装和上传成功后的自动解析状态展示，避免重复触发运行中作业，并展示可理解错误。
- 文档：同步更新 README、`.env.example`、端侧说明和必要的开发验证说明。
- 验收信号：当前用户可为自己的已上传且符合解析格式策略的文件创建解析作业；作业经 `BackgroundTasks` 执行后写入成功或失败状态；成功结果包含 Markdown、纯文本、Docling JSON 和结构片段；本地不会生成页面图、图表图片或表格截图；非归属文件无法解析或读取结果；不符合解析格式策略的文件即使已上传也会被解析入口拒绝。
- 回滚说明：回滚时撤销前端解析入口、后端解析路由/服务、Docling 依赖和相关配置，通过 Alembic downgrade 删除解析表；已写入的 `storage/parsed` 文本与 JSON 产物需要按目录清理策略单独处理，原始上传文件不受影响。
