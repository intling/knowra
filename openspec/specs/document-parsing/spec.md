# document-parsing Specification

## Purpose
TBD - created by archiving change add-document-parsing-docling. Update Purpose after archive.
## Requirements

### Requirement: 文档解析作业模型
系统 SHALL 持久化文档解析作业，并通过上传文件和当前用户归属支持异步状态追踪、错误诊断和后续重新解析。

#### Scenario: 创建解析作业表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_parse_jobs` 表
- **AND** `document_parse_jobs` 表 MUST 包含 `id`、`uploaded_file_id`、`owner_user_id`、`status`、`parser_name`、`parser_version`、`attempt_count`、`started_at`、`finished_at`、`error_code`、`error_message`、`created_at`、`updated_at` 字段

#### Scenario: 解析作业关联上传文件和当前用户
- **WHEN** 系统为已上传文件创建解析作业
- **THEN** 解析作业 MUST 保存对应 `uploaded_file_id`
- **AND** 解析作业的 `owner_user_id` MUST 来自上传文件归属或后端当前用户解析
- **AND** 系统 MUST NOT 使用客户端提交的用户归属字段决定解析作业归属

#### Scenario: 解析作业状态可追踪
- **WHEN** 解析作业被创建
- **THEN** 初始状态 MUST 为 `queued`
- **AND** 作业执行中 MUST 转换为 `running`
- **AND** 作业完成后 MUST 转换为 `succeeded` 或 `failed`
- **AND** 失败作业 MUST 保存可诊断的 `error_code` 或 `error_message`

### Requirement: 创建文档解析作业 API
系统 SHALL 提供 API，让当前用户为自己的已上传文件创建文档解析作业，并以异步任务语义返回作业状态。

#### Scenario: 当前用户为自己的上传文件创建解析作业
- **WHEN** 当前用户解析成功
- **AND** 上传文件属于当前用户且未删除
- **AND** 客户端调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** API MUST 返回 `202`
- **AND** 响应体 MUST 包含解析作业的 `id`、`uploaded_file_id`、`status`、`created_at`
- **AND** 响应体中的 `status` MUST 为 `queued` 或 `running`

#### Scenario: 当前用户不可用时拒绝创建解析作业
- **WHEN** 当前用户解析失败
- **AND** 客户端调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 创建无归属解析作业

#### Scenario: 不能解析其他用户的上传文件
- **WHEN** 当前用户解析成功
- **AND** 上传文件不属于当前用户
- **AND** 客户端调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 创建指向该上传文件的当前用户解析作业

#### Scenario: 不支持的文件类型无法创建解析作业
- **WHEN** 上传文件的内容类型或扩展名不属于文档解析支持范围
- **AND** 客户端调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** API MUST 返回 `415` 或等价的不支持类型错误
- **AND** 响应体 MUST 包含可诊断错误信息

#### Scenario: 运行中作业避免重复触发
- **WHEN** 某上传文件已经存在 `queued` 或 `running` 的解析作业
- **AND** 客户端再次调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** API MUST 返回 `409`
- **AND** 响应体 MUST 包含已有运行中解析作业信息
- **AND** 响应体 MUST 包含该上传文档的 `id`、`original_filename`、`content_type`、`byte_size` 和 `status`
- **AND** 系统 MUST NOT 为同一上传文件创建多个并发运行作业

### Requirement: 文档解析作业状态查询 API
系统 SHALL 提供解析作业查询 API，让当前用户查看自己解析作业的状态、错误和关联上传文件。

#### Scenario: 查询当前用户解析作业
- **WHEN** 当前用户解析成功
- **AND** 解析作业属于当前用户
- **AND** 客户端调用 `GET /api/document-parse-jobs/{job_id}`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含 `id`、`uploaded_file_id`、`status`、`error_code`、`error_message`、`started_at`、`finished_at`

#### Scenario: 不能查询其他用户解析作业
- **WHEN** 当前用户解析成功
- **AND** 解析作业不属于当前用户
- **AND** 客户端调用 `GET /api/document-parse-jobs/{job_id}`
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST NOT 暴露其他用户的解析作业细节

### Requirement: BackgroundTasks 测试版调度
系统 SHALL 在首版使用 FastAPI `BackgroundTasks` 调度解析作业，并保持任务执行逻辑可被未来独立 worker + 队列复用。

#### Scenario: 创建作业后提交后台任务
- **WHEN** `POST /api/uploads/{upload_id}/parse` 成功创建解析作业
- **THEN** 系统 MUST 将作业 ID 提交给 FastAPI `BackgroundTasks`
- **AND** API MUST 在后台解析完成前返回异步响应

#### Scenario: 后台任务重新读取持久化作业
- **WHEN** 后台解析任务开始执行
- **THEN** 任务 MUST 使用作业 ID 从数据库重新读取解析作业和上传文件
- **AND** 任务 MUST NOT 依赖请求上下文中的 ORM 对象继续存在

#### Scenario: 后台任务写入最终状态
- **WHEN** 后台解析任务执行成功
- **THEN** 作业状态 MUST 更新为 `succeeded`
- **AND** 系统 MUST 保存解析结果
- **WHEN** 后台解析任务执行失败
- **THEN** 作业状态 MUST 更新为 `failed`
- **AND** 系统 MUST 保存可诊断错误

### Requirement: Docling 文档解析适配
系统 SHALL 通过封装的解析适配器使用 Docling 处理目标文档格式，并向项目内部返回稳定的规范化解析结果。

#### Scenario: 解析支持的文档格式
- **WHEN** 上传文件类型为 PDF、DOCX、PPTX、Markdown 或 TXT
- **AND** 系统执行解析作业
- **THEN** 解析适配器 MUST 生成 Markdown、纯文本和结构化 JSON 产物内容
- **AND** 解析结果 MUST 保留足以追溯到原始文件、页码或结构位置的元数据

#### Scenario: Docling SDK 类型不泄露到 API 响应
- **WHEN** 解析适配器完成 Docling 转换
- **THEN** 服务层 MUST 接收项目内定义的规范化结果
- **AND** API 响应 MUST NOT 直接暴露第三方 SDK 内部对象

#### Scenario: TXT 解析保持统一输出契约
- **WHEN** 上传文件为 TXT
- **AND** 当前 Docling 版本不提供稳定 TXT 输入能力
- **THEN** 系统 MUST 在同一解析适配边界内生成等价的 Markdown、纯文本和结构化 JSON 产物内容
- **AND** 对外作业状态和解析结果契约 MUST 与其他格式保持一致

### Requirement: 解析格式安全校验
系统 SHALL 在创建解析作业前执行独立于上传默认白名单的解析格式策略校验，并使用轻量服务端识别降低错误或伪造类型进入解析器的风险。

#### Scenario: 解析入口使用独立允许列表
- **WHEN** 客户端调用 `POST /api/uploads/{upload_id}/parse`
- **THEN** 系统 MUST 使用解析允许内容类型或解析允许扩展名配置判断该文件是否可解析
- **AND** 系统 MUST NOT 仅因为文件已成功上传就跳过解析格式校验

#### Scenario: PDF 通过轻量文件头识别
- **WHEN** 上传文件被识别为 PDF 解析候选
- **THEN** 系统 MUST 在执行 Docling 转换前验证文件头或等价轻量信号符合 PDF 格式
- **AND** 不符合 PDF 格式的文件 MUST 被解析入口拒绝

#### Scenario: Office 文档通过 OOXML 容器识别
- **WHEN** 上传文件被识别为 DOCX 或 PPTX 解析候选
- **THEN** 系统 MUST 在执行 Docling 转换前验证文件为 ZIP/OOXML 容器
- **AND** DOCX 候选 MUST 包含 Word 文档关键结构
- **AND** PPTX 候选 MUST 包含 PowerPoint 文档关键结构
- **AND** 不符合对应结构的文件 MUST 被解析入口拒绝

#### Scenario: 文本类文件通过有限采样识别
- **WHEN** 上传文件被识别为 TXT 或 Markdown 解析候选
- **THEN** 系统 MUST 在执行解析前验证文件在采样范围内可作为文本读取
- **AND** 不符合文本读取策略的文件 MUST 被解析入口拒绝

### Requirement: 解析产物存储
系统 SHALL 将解析产物保存到应用内解析产物存储位置，并通过稳定 `storage_key` 关联解析结果。

#### Scenario: 成功解析后保存三类文本和结构化产物
- **WHEN** 文档解析作业成功
- **THEN** 系统 MUST 保存 Markdown 产物
- **AND** 系统 MUST 保存纯文本产物
- **AND** 系统 MUST 保存 Docling JSON 或等价结构化 JSON 产物
- **AND** 解析结果 MUST 保存每个产物对应的 `storage_key`

#### Scenario: 不保存派生图片资产
- **WHEN** 文档解析作业成功
- **THEN** 系统 MUST NOT 在解析产物目录保存 PDF 页面图
- **AND** 系统 MUST NOT 保存图表图片
- **AND** 系统 MUST NOT 保存表格截图

#### Scenario: 解析产物目录可配置
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取解析产物存储目录
- **AND** 解析产物存储服务 MUST 使用该目录保存 Markdown、纯文本和结构化 JSON 产物

### Requirement: 解析结果和结构片段模型
系统 SHALL 持久化成功解析结果和粗粒度结构片段，以便后续分块、索引、预览和来源追溯复用。

#### Scenario: 创建解析结果表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `parsed_documents` 表
- **AND** `parsed_documents` 表 MUST 包含 `id`、`uploaded_file_id`、`parse_job_id`、`owner_user_id`、`source_checksum_sha256`、`markdown_storage_key`、`text_storage_key`、`docling_json_storage_key`、`title`、`page_count`、`metadata_json`、`created_at` 字段

#### Scenario: 创建结构片段表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_segments` 表
- **AND** `document_segments` 表 MUST 包含 `id`、`parsed_document_id`、`owner_user_id`、`sequence_index`、`segment_type`、`page_no`、`heading_path`、`text`、`metadata_json`、`created_at` 字段

#### Scenario: 成功解析后保存结构片段
- **WHEN** 文档解析作业成功
- **THEN** 系统 MUST 为解析结果保存一个或多个结构片段
- **AND** 每个结构片段 MUST 包含稳定顺序字段
- **AND** 每个结构片段 MUST 保留可用于来源追溯的文档位置元数据

### Requirement: 读取解析结果
系统 SHALL 提供 API 读取当前用户上传文件的最新成功解析结果和结构片段。

#### Scenario: 读取上传文件的最新解析结果
- **WHEN** 当前用户解析成功
- **AND** 上传文件属于当前用户
- **AND** 该上传文件存在成功解析结果
- **AND** 客户端调用 `GET /api/uploads/{upload_id}/parsed-document`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含解析结果 ID、上传文件 ID、产物 `storage_key`、文档元数据和结构片段数量

#### Scenario: 读取不存在的解析结果
- **WHEN** 上传文件属于当前用户
- **AND** 该上传文件尚无成功解析结果
- **AND** 客户端调用 `GET /api/uploads/{upload_id}/parsed-document`
- **THEN** API MUST 返回非 2xx 状态码或明确空状态
- **AND** 响应体 MUST 表达文档尚未完成解析

#### Scenario: 分页读取结构片段
- **WHEN** 当前用户解析成功
- **AND** 解析结果属于当前用户
- **AND** 客户端调用 `GET /api/parsed-documents/{id}/segments`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 按 `sequence_index` 返回结构片段
- **AND** 响应体 MUST 支持分页或限制返回数量

### Requirement: 文档解析配置
系统 SHALL 通过配置管理解析开关、资源限制、Docling 行为和调度器类型，避免在业务代码中硬编码环境差异。

#### Scenario: 配置解析开关
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取文档解析启用开关
- **AND** 当解析被禁用时，创建解析作业 API MUST 返回非 2xx 状态码并表达解析不可用

#### Scenario: 配置解析资源限制
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取最大解析字节数和最大页数
- **AND** 最大解析字节数默认值 MUST 为 `50 * 1024 * 1024`
- **AND** 最大页数默认值 MUST 为 `100`
- **AND** 解析服务 MUST 使用这些限制拒绝超限文件

#### Scenario: 配置 Docling 行为
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取 OCR 开关和 Docling 运行缓存目录
- **AND** 首版默认 OCR MUST 关闭

#### Scenario: 配置解析允许格式
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取解析允许内容类型或解析允许扩展名
- **AND** 解析服务 MUST 使用该配置决定文件是否可创建解析作业
- **AND** 解析允许格式配置 MUST 独立于上传默认允许内容类型配置

#### Scenario: 配置解析调度器
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取解析调度器类型
- **AND** 首版默认调度器 MUST 为 FastAPI `BackgroundTasks`

### Requirement: 前端解析状态体验
前端 SHALL 在用户上传资料成功后自动提交文档解析作业，并展示加载、完成、失败和重试反馈。

#### Scenario: 上传完成后自动提交解析
- **WHEN** 用户成功上传支持解析的文件
- **THEN** 前端 MUST 调用 `POST /api/uploads/{upload_id}/parse`
- **AND** 前端 MUST 展示自动触发后的解析状态

#### Scenario: 解析中防止重复触发
- **WHEN** 解析作业处于 `queued` 或 `running`
- **THEN** 前端 MUST 展示解析中状态
- **AND** 前端 MUST 防止用户重复触发同一文件解析

#### Scenario: 解析成功后展示完成状态
- **WHEN** 解析作业状态为 `succeeded`
- **THEN** 前端 MUST 展示解析完成反馈
- **AND** 前端 MUST 提供查看解析预览或继续后续流程的入口

#### Scenario: 解析失败后展示错误和重试可能
- **WHEN** 解析作业状态为 `failed`
- **THEN** 前端 MUST 展示用户可理解的错误反馈
- **AND** 前端 MUST 保留用户重新触发解析或重新上传文件的可能性
