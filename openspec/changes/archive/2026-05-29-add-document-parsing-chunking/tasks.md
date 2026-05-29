## 1. 契约与测试准备

- [x] 1.1 阅读本变更 `proposal.md`、`design.md` 和 specs，确认实现范围不包含 embedding、检索、RAG、OCR 或异步任务队列
- [x] 1.2 选择 PDF、DOCX、PPT/PPTX 解析依赖和 BPE tokenizer 依赖，并验证它们与 Python 3.14.5、uv、pytest 兼容
- [x] 1.3 更新后端依赖清单和锁文件，加入解析依赖与 BPE tokenizer 依赖
- [x] 1.4 RED 阶段：新增 Alembic 迁移测试，覆盖 `documents`、`document_chunks` 表、外键、唯一约束和索引，运行并确认以预期原因失败
- [x] 1.5 RED 阶段：新增文档处理服务测试，覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX 成功解析和 chunk 生成，运行并确认以预期原因失败
- [x] 1.6 RED 阶段：新增失败路径测试，覆盖不支持类型、扫描版或空文本 PDF、原始文件缺失、空解析结果和解析异常，运行并确认以预期原因失败
- [x] 1.7 RED 阶段：新增 API 测试，覆盖 `POST /api/documents`、`GET /api/documents`、`GET /api/documents/{id}`、`GET /api/documents/{id}/chunks`、`404`、`409`、`415`、`500`，运行并确认以预期原因失败
- [x] 1.8 RED 阶段：新增前端资料列表测试，覆盖 parsed/failed 文档展示、失败原因展示和重复处理冲突反馈，运行并确认以预期原因失败

## 2. 后端数据模型与迁移

- [x] 2.1 新增 `Document` 和 `DocumentChunk` SQLModel 模型，包含规格要求的字段、外键、状态和时间字段
- [x] 2.2 新增 Alembic migration，创建 `documents` 与 `document_chunks` 表、`uploaded_file_id` 唯一约束、`document_id + chunk_index` 唯一约束和查询索引
- [x] 2.3 更新模型导出与数据库初始化路径，确保迁移和测试能发现新模型
- [x] 2.4 运行迁移相关测试，使第 1.4 项 RED 测试进入 GREEN

## 3. 文档解析与 BPE 分块服务

- [x] 3.1 扩展或复用上传文件存储读取抽象，提供按 `storage_key` 安全读取原始文件的接口
- [x] 3.2 实现 parser registry 和统一 `ParsedDocument` 输出结构
- [x] 3.3 实现 TXT parser，覆盖 UTF-8 解码成功和失败语义
- [x] 3.4 实现 Markdown parser，保留正文并提取标题路径元数据
- [x] 3.5 实现 PDF parser，逐页抽取文本并记录页码 source locator，无法抽取有效文本时返回失败原因
- [x] 3.6 实现 DOCX parser，抽取标题、段落和主要表格文本，并记录段落或结构路径 source locator
- [x] 3.7 实现 PPT/PPTX parser，按 slide index 抽取标题、文本框和备注文本
- [x] 3.8 实现 BPE tokenizer 适配器，提供 token 计数、窗口切分、名称和版本信息
- [x] 3.9 实现确定性 chunker，按结构边界和 BPE token 窗口生成 chunk，写入 token 数、字符范围、hash 和 source locator
- [x] 3.10 运行解析、BPE 和 chunk 服务测试，使第 1.5、1.6 项 RED 测试进入 GREEN

## 4. 文档处理 API 与状态语义

- [x] 4.1 新增文档处理 request/response schema，覆盖文档元数据、chunk 响应、failed 文档和 `existing_document` 冲突响应
- [x] 4.2 实现文档处理服务，校验当前用户、上传文件归属、`stored` 状态和重复处理冲突
- [x] 4.3 实现 `POST /api/documents`，成功返回 `201`，重复处理返回 `409 Conflict` 且携带已有文档元数据
- [x] 4.4 实现 `GET /api/documents`，返回当前用户的 parsed 与 failed 文档列表，并包含 failed 失败原因
- [x] 4.5 实现 `GET /api/documents/{id}`，只返回当前用户可访问的文档详情
- [x] 4.6 实现 `GET /api/documents/{id}/chunks`，仅对 parsed 文档返回按 `chunk_index` 排序的 chunks
- [x] 4.7 确保 failed 文档不会被 chunks 查询或后续索引消费路径当作可检索内容
- [x] 4.8 运行 API 测试，使第 1.7 项 RED 测试进入 GREEN

## 5. 上传配置与前端资料列表

- [x] 5.1 更新后端上传允许内容类型默认配置和 `.env.example`，覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX
- [x] 5.2 更新前端 API client，新增 documents 相关请求和 `409 existing_document` 错误响应处理
- [x] 5.3 更新资料列表状态模型，支持 parsed 与 failed 文档以及失败原因字段
- [x] 5.4 更新资料列表 UI，展示 failed 文档状态、来源文件名、失败原因、创建时间和重试入口
- [x] 5.5 更新重复处理交互，收到 `409 Conflict` 时展示已有文档信息或跳转入口
- [x] 5.6 运行前端资料列表测试，使第 1.8 项 RED 测试进入 GREEN

## 6. 文档与验证

- [x] 6.1 更新根目录 `README.md`，说明上传后文档处理流程和新增 API
- [x] 6.2 更新 `backend/README.md`，说明新增依赖、环境变量、迁移、文档处理 API 和验证命令
- [x] 6.3 如前端资料列表使用方式变化，更新 `front/README.md` 或相关前端文档
- [x] 6.4 运行后端质量门禁：`uv run ruff check .`
- [x] 6.5 运行后端格式检查：`uv run ruff format --check .`
- [x] 6.6 运行后端测试：`uv run pytest`
- [x] 6.7 运行前端质量门禁：`npm run lint`
- [x] 6.8 运行前端测试：`npm run test`
- [x] 6.9 运行前端构建：`npm run build`
- [x] 6.10 执行本地 API smoke check：上传样例 TXT、Markdown、PDF、DOCX、PPT/PPTX 后创建文档，并验证 parsed/failed 列表、chunks 查询和重复处理 `409` 响应
