## Why

knowra 已经具备原始文件上传与存储能力，但上传文件还不能转化为可检索、可追溯、可问答的知识单元。需要新增文件解析与分块能力，把已上传资料转化为稳定的文档记录和 chunk，为后续 embedding、检索和 RAG 引用提供数据基础。

## What Changes

- 新增文档处理后端能力：消费当前用户已上传且 `status = stored` 的 `uploaded_files`，生成 `documents` 和 `document_chunks`。
- 首批支持 TXT、Markdown、PDF、DOCX、PPT/PPTX 的文本解析；PDF 首批只支持具备文本层的内容，不做 OCR。
- 使用 BPE tokenizer 控制 chunk 大小和重叠窗口，并记录 tokenizer 名称、版本、token 数、chunker 版本和来源定位。
- 新增文档处理 API：
  - `POST /api/documents` 从 `uploaded_file_id` 创建文档与 chunks。
  - `GET /api/documents` 返回当前用户的资料列表，包含 `parsed` 和 `failed` 文档。
  - `GET /api/documents/{id}` 返回文档元数据。
  - `GET /api/documents/{id}/chunks` 返回文档 chunks。
- 重复处理同一 `uploaded_file_id` 时返回 `409 Conflict`，响应体携带已有文档元数据，避免重复 chunks 污染后续索引。
- 解析失败需要生成或保留 `failed` 文档元数据，并在前端资料列表中展示失败原因；`failed` 文档不得进入 embedding、检索或 RAG 消费链路。
- 上传配置需要允许本变更首批支持的内容类型进入上传存储流程。
- 本变更不实现 embedding、pgvector 写入、检索、重排、RAG、OCR、图片解析、PDF 复杂版面重建、Office 视觉版面恢复或后台任务队列。

## Capabilities

### New Capabilities

- `document-processing`: 从已上传原始文件创建文档记录和可追溯 chunks，并提供文档处理 API、状态语义、失败展示和 BPE 分块契约。

### Modified Capabilities

- `file-upload-storage`: 上传允许内容类型需要覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX，使这些文件能够被保存为后续文档处理输入。

## Impact

- 后端数据模型：新增 `documents`、`document_chunks` 表、外键、索引、状态字段、parser/chunker/tokenizer 版本字段和来源定位 JSON 字段，需要 Alembic migration。
- 后端服务：新增 parser registry、TXT/Markdown/PDF/DOCX/PPT 解析器、BPE tokenizer 适配、确定性 chunker、文档处理服务和资料列表查询服务。
- 后端 API：新增 `/api/documents` 相关路由、请求/响应 schema、`404`、`409`、`415`、`500` 等错误分支。
- 依赖与配置：新增 PDF、Office 文档解析依赖和 BPE tokenizer 依赖；更新上传允许内容类型配置与 `.env.example`。
- 前端 UX：资料列表需要展示 `parsed` 和 `failed` 文档，重复处理时可根据 `409` 响应中的已有文档元数据展示或跳转。
- 文档：同步更新根 README、`backend/README.md`，必要时更新 `front/README.md` 或相关前端文档。
- 验收信号：迁移可执行；TXT、Markdown、PDF、DOCX、PPT/PPTX 成功生成文档与 chunks；重复处理返回 `409` 且带已有文档元数据；failed 文档出现在资料列表且不会被检索消费。
