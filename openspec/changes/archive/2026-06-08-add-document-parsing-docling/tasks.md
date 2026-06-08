## 1. 后端契约与红测试

- [x] 1.1 准备最小解析 fixture，覆盖 `.txt`、`.md`、`.docx`、`.pptx` 和文本型 `.pdf`，并避免大文件或 OCR fixture 进入默认测试集。
- [x] 1.2 为上传与解析格式策略分离编写失败测试，确认本变更不强制扩展上传默认白名单，并覆盖解析允许内容类型、解析允许扩展名和配置覆盖后的拒绝行为。
- [x] 1.3 为解析配置编写失败测试，覆盖解析开关、解析产物目录、最大解析字节数默认 50MB、最大页数默认 100 页、OCR 默认关闭、Docling 缓存目录和 `DOCUMENT_PARSE_DISPATCHER` 默认值。
- [x] 1.4 为 `DocumentParseJob`、`ParsedDocument`、`DocumentSegment` 模型和 Alembic migration 编写失败测试，覆盖字段、外键、状态、索引和 downgrade。
- [x] 1.5 为解析服务编写失败测试，覆盖当前用户只能解析自己的上传文件、上传文件不存在、文件已删除、不支持类型、重复运行中作业返回冲突且带文档信息，以及超限文件。
- [x] 1.6 为解析格式安全校验和 Docling 适配器编写失败测试，覆盖 PDF 文件头识别、DOCX/PPTX OOXML 容器识别、TXT/Markdown 文本采样、支持格式映射、TXT 兜底输出契约、异常转换、Markdown/Text/JSON 产物生成，以及不写入页面图、图表图片或表格截图。
- [x] 1.7 为 BackgroundTasks dispatcher 编写失败测试，覆盖成功创建作业后注册 `run_parse_job(job_id)`、任务重新读取数据库作业、成功/失败状态写回和任务幂等跳过。
- [x] 1.8 为解析 API 编写失败测试，覆盖 `POST /api/uploads/{upload_id}/parse` 的 `202`、当前用户不可用、非归属文件、不支持类型、重复运行中作业 `409` 且带文档信息，以及 `GET /api/document-parse-jobs/{job_id}` 权限和响应结构。
- [x] 1.9 为解析结果读取 API 编写失败测试，覆盖最新成功解析结果、未完成解析空状态、结构片段分页和非归属访问拒绝。
- [x] 1.10 运行新增后端测试并确认因解析能力尚未实现而 RED，然后停止在红测试评审点，提示用户评审并回复“继续”后再进入实现阶段。

## 2. 后端实现

- [x] 2.1 增加 Docling 依赖并更新后端锁文件，确认依赖安装与 Python 3.14 环境兼容。
- [x] 2.2 在 `backend/app/core/config.py` 和 `backend/.env.example` 中增加解析配置，包含解析允许内容类型、解析允许扩展名和调度器配置；上传默认允许内容类型不因本变更强制放宽。
- [x] 2.3 新增解析相关 SQLModel 模型，并确保模型被 Alembic metadata 发现。
- [x] 2.4 新增 Alembic migration 创建 `document_parse_jobs`、`parsed_documents`、`document_segments` 表、外键和索引，并实现 downgrade。
- [x] 2.5 新增解析 API schema，统一作业状态、错误、解析结果和结构片段分页响应。
- [x] 2.6 新增解析产物存储服务，写入 `content.md`、`content.txt`、`docling.json`，并禁止保存派生图片资产。
- [x] 2.7 新增 Docling 解析适配器，封装 `DocumentConverter`、格式映射、资源限制、OCR 开关、TXT 兜底和异常转换。
- [x] 2.8 新增文档解析业务服务，编排上传记录读取、权限校验、作业创建、重复作业处理、解析结果持久化和错误状态写回。
- [x] 2.9 新增 BackgroundTasks dispatcher 和 `run_parse_job(job_id)` 任务入口，并保持任务入口可被未来队列 worker 复用。
- [x] 2.10 新增 `/api/uploads/{upload_id}/parse`、`/api/document-parse-jobs/{job_id}`、`/api/uploads/{upload_id}/parsed-document`、`/api/parsed-documents/{id}/segments` 路由并注册到 API router。
- [x] 2.11 运行后端相关测试，确认解析模型、服务、适配器、API 和上传类型扩展达到 GREEN。

## 3. 前端契约与红测试

- [x] 3.1 为前端解析 API 封装编写失败测试，覆盖创建解析作业、查询作业状态、读取解析结果、读取结构片段和错误响应解析。
- [x] 3.2 为上传后解析流程编写失败测试，覆盖上传成功后展示解析入口、触发解析、解析中禁用重复触发、解析成功展示完成状态。
- [x] 3.3 为前端错误状态编写失败测试，覆盖当前用户不可用、不支持类型、解析失败、重复运行中作业和网络错误反馈。
- [x] 3.4 为前端文件接受范围和服务端拒绝反馈编写失败测试，确认 UI 不把解析目标格式等同于当前部署已允许上传格式，并能展示上传或解析格式不支持错误。
- [x] 3.5 运行新增前端测试并确认因解析前端能力尚未实现而 RED，然后停止在红测试评审点，提示用户评审并回复“继续”后再进入实现阶段。

## 4. 前端实现

- [x] 4.1 新增 document parsing API 类型和请求封装，继续使用 `VITE_API_BASE_URL` 和 `/api` 前缀约定。
- [x] 4.2 更新上传后的 UI 状态，展示等待解析、解析中、解析完成和解析失败反馈。
- [x] 4.3 增加解析触发和状态轮询或刷新逻辑，防止同一上传文件在运行中重复触发解析。
- [x] 4.4 增加解析结果预览入口或轻量完成状态展示，避免承诺 RAG 问答能力。
- [x] 4.5 更新前端文件接受类型和用户可理解的格式说明，使其与当前上传配置和解析策略保持一致，不默认承诺所有解析目标格式均可上传。
- [x] 4.6 运行前端相关测试，确认解析状态体验达到 GREEN。

## 5. 文档与配置同步

- [x] 5.1 更新后端 README 或根 README，说明解析 API、解析配置、Docling 依赖、`BackgroundTasks` 限制和解析产物目录。
- [x] 5.2 更新 `.env.example`，补充解析开关、资源限制、Docling 缓存目录、调度器类型、解析允许格式配置，以及按需显式放开上传 MIME 的示例说明。
- [x] 5.3 更新前端 README 或相关文档，说明上传后解析状态和支持文件类型。
- [x] 5.4 在文档中明确首版不保存 PDF 页面图、图表图片、表格截图等派生图片资产。
- [x] 5.5 如果实现过程中发现 Docling 版本、TXT 支持或队列边界与设计不匹配，先更新本 OpenSpec 变更再继续实现。

## 6. 集成验证与收尾

- [x] 6.1 运行 `uv run ruff check .` 验证后端静态检查。
- [x] 6.2 运行 `uv run ruff format --check .` 验证后端格式。
- [x] 6.3 运行 `uv run pytest` 验证后端测试。
- [x] 6.4 运行 Alembic upgrade/downgrade 验证解析 migration 可正向和反向执行。
- [x] 6.5 运行 `npm run lint` 验证前端静态检查。
- [x] 6.6 运行 `npm run test` 验证前端测试。
- [x] 6.7 运行 `npm run build` 验证前端构建。
- [x] 6.8 启动本地前后端并执行 smoke check：在测试环境显式允许目标上传类型后上传样例文件、触发解析、查看作业状态、确认生成 Markdown/Text/JSON 产物且未生成派生图片资产；同时验证伪造 MIME 或结构不匹配文件会被解析入口拒绝。

## 7. 前端自动解析调整

- [x] 7.1 为上传成功后自动提交解析作业编写失败测试，并确认前端测试因尚未自动调用解析 API 而 RED。
- [x] 7.2 更新首页上传成功流程，自动调用 `POST /api/uploads/{upload_id}/parse`，普通成功路径不再要求用户点击解析。
- [x] 7.3 运行前端相关测试、静态检查和构建，确认自动解析交互达到 GREEN。
