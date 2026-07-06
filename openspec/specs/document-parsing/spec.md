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

### Requirement: 解析内部结果携带 transient DoclingDocument
系统 SHALL 在 Docling 解析适配器的内部结果中同时提供可持久化解析 payload 和只供当前后台任务使用的 transient `DoclingDocument`；Markdown 解析 SHALL 产出 transient `DoclingDocument`，TXT 解析 SHALL 使用纯文本兜底而不要求产出 transient `DoclingDocument`。

新增日期：2026-06-13；来源变更：add-document-chunking-docling。

#### Scenario: Docling 解析返回 transient 文档对象
- **WHEN** Docling 解析适配器成功转换支持格式的文档
- **THEN** 解析内部结果 MUST 包含可持久化的 Markdown、纯文本、Docling JSON 和结构片段 payload
- **AND** 解析内部结果 MUST 包含当前解析运行内存中的 transient `DoclingDocument`

#### Scenario: Markdown 解析产出 transient 文档对象
- **WHEN** 上传文件为 Markdown
- **AND** 系统执行解析作业
- **THEN** 解析适配器 MUST 通过 Docling 生成当前解析运行内存中的 transient `DoclingDocument`
- **AND** 解析内部结果 MUST 保留该 transient `DoclingDocument` 以供自动分块使用
- **AND** 解析内部结果 MUST 仍包含可持久化的 Markdown、纯文本、Docling JSON 或等价结构化 JSON、结构片段 payload

#### Scenario: TXT 解析使用纯文本兜底
- **WHEN** 上传文件为 TXT
- **AND** 当前解析路径无法稳定产出 transient `DoclingDocument`
- **THEN** 解析内部结果 MUST 包含由原始纯文本生成的 Markdown、纯文本、等价结构化 JSON 和结构片段 payload
- **AND** 解析内部结果 MUST 明确表达缺少 transient `DoclingDocument`
- **AND** 系统 MUST NOT 为 TXT 从 `docling.json`、pickle 或其他已落地解析产物还原 transient `DoclingDocument`

#### Scenario: transient 文档对象不被持久化或暴露
- **WHEN** 系统保存解析产物、解析结果记录或返回解析 API 响应
- **THEN** 系统 MUST NOT 将 transient `DoclingDocument` 写入数据库
- **AND** 系统 MUST NOT 将 transient `DoclingDocument` 写入文件存储
- **AND** 系统 MUST NOT 通过 API 响应暴露 transient `DoclingDocument`

### Requirement: 解析成功路径接入自动分块
系统 SHALL 在解析后台任务成功保存解析结果后，优先将同一任务内的 transient `DoclingDocument` 交给文档分块服务执行首次分块；当 TXT 解析没有 transient `DoclingDocument` 时，系统 SHALL 使用纯文本兜底路径执行首次分块。

新增日期：2026-06-13；来源变更：add-document-chunking-docling。

#### Scenario: 解析任务保存结果后触发分块服务
- **WHEN** `run_parse_job` 成功保存 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果包含 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务
- **AND** 解析任务 MUST 将同一个 transient `DoclingDocument` 对象传递给分块服务

#### Scenario: Markdown 解析后自动使用 DoclingDocument 分块
- **WHEN** `run_parse_job` 成功保存 Markdown 文件的 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果包含 Markdown 解析产生的 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务
- **AND** 解析任务 MUST 将该 transient `DoclingDocument` 传递给分块服务执行首次分块

#### Scenario: TXT 解析后使用纯文本兜底分块
- **WHEN** `run_parse_job` 成功保存 TXT 文件的 `parsed_documents` 和 `document_segments`
- **AND** 分块功能配置为启用
- **AND** 解析内部结果不包含 transient `DoclingDocument`
- **THEN** 解析任务 MUST 调用文档分块服务的纯文本兜底路径
- **AND** 纯文本兜底路径 MUST 使用解析结果中的纯文本或结构片段生成首次 chunk
- **AND** 解析任务 MUST NOT 为 TXT 从 `docling.json`、pickle 或其他已落地解析产物还原 transient `DoclingDocument`

#### Scenario: 分块禁用时解析保持成功
- **WHEN** `run_parse_job` 成功保存解析结果
- **AND** 分块功能配置为禁用
- **THEN** 解析作业 MUST 保持 `succeeded`
- **AND** 系统 MUST NOT 创建文档分块作业

#### Scenario: 分块失败不回滚解析结果
- **WHEN** `run_parse_job` 已成功保存解析结果
- **AND** 自动分块执行失败
- **THEN** 解析作业 MUST 保持 `succeeded`
- **AND** 分块作业 MUST 记录为 `failed`
- **AND** 已保存的 `parsed_documents` 和 `document_segments` MUST 保持可查询

### Requirement: 文档模型启动配置隔离
系统 SHALL 使用独立的 `DOCUMENT_MODEL_*` 环境变量配置启动后的文档模型准备流程，并且 MUST NOT 复用、扩展或 fallback 到既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 变量作为模型 bootstrap 配置来源。

#### Scenario: 读取独立模型准备配置
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_ENABLED`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_HF_ENDPOINT`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_TOKENIZER_NAME`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`

#### Scenario: 不复用既有解析或分块变量
- **WHEN** `DOCUMENT_MODEL_*` 变量未显式配置
- **AND** 既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 变量已配置为非默认值
- **THEN** 模型 bootstrap MUST 使用 `DOCUMENT_MODEL_*` 默认值或显式配置值
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 Docling artifacts 目录 fallback
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_CHUNK_TOKENIZER_MODEL` 作为 tokenizer 名称 fallback
- **AND** 模型 bootstrap MUST NOT 使用任何既有解析或分块变量作为下载策略、镜像地址或模型目录来源

#### Scenario: 配置 Hugging Face 镜像地址
- **WHEN** `DOCUMENT_MODEL_HF_ENDPOINT` 配置为非空地址
- **AND** 模型 bootstrap 需要检查或下载 Hugging Face 模型
- **THEN** 系统 MUST 在调用 Hugging Face Hub 或 Docling 下载逻辑前使用该地址配置 Hugging Face endpoint
- **AND** 系统 MUST NOT 在代码中硬编码镜像地址

### Requirement: Docling 模型启动准备
系统 SHALL 在后端应用启动后的模型 bootstrap 流程中检查 Docling 文档解析所需 artifacts，并按配置策略处理缺失模型。

#### Scenario: Docling 模型已存在时启动为 ready
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` 中已存在 `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS` 声明的全部 Docling artifacts
- **THEN** 模型 bootstrap MUST 将 Docling readiness 标记为 `ready`
- **AND** 系统 MUST 记录结构化日志表达 Docling 模型已可用

#### Scenario: check_only 策略发现模型缺失
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `check_only`
- **AND** 一个或多个 required Docling 模型缺失
- **THEN** 模型 bootstrap MUST NOT 尝试下载缺失模型
- **AND** 模型 bootstrap MUST 将 Docling readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含缺失模型清单

#### Scenario: download_missing 策略下载缺失模型
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `download_missing`
- **AND** 一个或多个 required Docling 模型缺失
- **THEN** 模型 bootstrap MUST 将缺失模型下载到 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`
- **AND** 下载完成后系统 MUST 重新检查 required Docling 模型
- **AND** 全部 required Docling 模型可用时 readiness MUST 标记为 `ready`

#### Scenario: fail_fast 策略阻止不可用模型启动
- **WHEN** 模型 bootstrap 完成后 Docling readiness 为 `unavailable`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY` 为 `fail_fast`
- **THEN** 后端应用 MUST 中止启动
- **AND** 系统 MUST 记录结构化错误日志表达缺失模型和配置建议

#### Scenario: degraded 策略允许降级启动
- **WHEN** 模型 bootstrap 完成后 Docling readiness 为 `unavailable`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY` 为 `degraded`
- **THEN** 后端应用 MUST 继续启动
- **AND** 系统 MUST 保留 Docling readiness 的不可用状态供解析任务读取
- **AND** 系统 MUST 记录结构化告警日志表达后续解析可能失败

#### Scenario: 禁用模型 bootstrap
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `false`
- **THEN** 系统 MUST 跳过启动模型检查和下载
- **AND** readiness MUST 标记为 `skipped`
- **AND** 系统 MUST NOT 因未执行模型 bootstrap 而复用既有解析或分块变量作为替代配置

### Requirement: 解析任务使用模型 readiness
系统 SHALL 在执行需要 Docling 模型 artifacts 的文档解析前读取启动模型 readiness，并在模型不可用时产生明确的模型不可用错误。

#### Scenario: 模型 ready 时使用启动准备目录解析
- **WHEN** 文档解析作业需要 Docling 模型 artifacts
- **AND** Docling readiness 为 `ready`
- **THEN** 解析适配器 MUST 使用 `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` 作为 Docling artifacts 目录
- **AND** 解析适配器 MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为该解析运行的模型 artifacts 目录

#### Scenario: 模型 unavailable 时解析作业失败为模型不可用
- **WHEN** 文档解析作业需要 Docling 模型 artifacts
- **AND** Docling readiness 为 `unavailable`
- **THEN** 系统 MUST 将解析作业状态更新为 `failed`
- **AND** 解析作业 `error_code` MUST 为 `model_unavailable`
- **AND** 解析作业 `error_message` MUST 包含缺失模型或模型准备失败原因
- **AND** 系统 MUST NOT 在该解析作业内触发 Docling 或 Hugging Face 的隐式网络下载

#### Scenario: 不需要 Docling artifacts 的文本解析不被 Docling readiness 阻塞
- **WHEN** 上传文件可以通过项目内纯文本兜底路径解析
- **AND** Docling readiness 为 `unavailable`
- **THEN** 系统 MUST 允许该解析路径继续执行
- **AND** 系统 MUST NOT 因 Docling artifacts 缺失而拒绝纯文本兜底解析

### Requirement: 现有健康检查暴露文档模型 readiness
系统 SHALL 复用现有 `GET /api/health` 暴露文档模型 readiness 摘要，并且 MUST NOT 新增独立的 `/api/health/document-models` endpoint。

#### Scenario: 健康检查返回模型 ready 摘要
- **WHEN** 后端应用启动后文档模型 bootstrap readiness 为 `ready`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 保留既有健康检查字段
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 表达 Docling artifacts 和 tokenizer 均为 `ready`

#### Scenario: 健康检查返回模型 degraded 摘要
- **WHEN** 后端应用以 `degraded` 策略启动
- **AND** 文档模型 bootstrap readiness 为 `unavailable`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 包含不可用状态和缺失模型诊断

#### Scenario: 健康检查返回模型 skipped 摘要
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `false`
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含文档模型 readiness 摘要
- **AND** 文档模型 readiness 摘要 MUST 表达模型 bootstrap 已跳过

#### Scenario: 不新增独立模型健康检查 endpoint
- **WHEN** 客户端调用 `GET /api/health/document-models`
- **THEN** 系统 MUST NOT 提供该 endpoint 作为本变更的公共 API
- **AND** 模型 readiness MUST 只能通过既有 `GET /api/health` 的响应摘要暴露

### Requirement: Docling 模型内存异步预加载
系统 SHALL 在文档模型文件 bootstrap ready 后异步加载 Docling PDF 解析所需模型到进程内存，并且 MUST NOT 因内存预加载阻塞 FastAPI 应用启动完成。

#### Scenario: 文件模型 ready 后进入异步加载状态
- **WHEN** 后端启动阶段完成文档模型文件 bootstrap
- **AND** Docling artifacts readiness 为 `ready`
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `loading`
- **AND** 系统 MUST 启动后台任务加载 Docling PDF converter/pipeline
- **AND** FastAPI 应用启动 MUST NOT 等待该后台任务完成

#### Scenario: Docling 内存加载成功
- **WHEN** Docling 后台预加载任务成功初始化 PDF converter/pipeline
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `ready`
- **AND** 系统 MUST 保留已初始化的 converter 供后续解析复用
- **AND** 系统 MUST 记录结构化日志表达 Docling 模型已加载到内存

#### Scenario: Docling 内存加载失败
- **WHEN** Docling 后台预加载任务失败
- **THEN** 系统 MUST 将 Docling 内存 readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含加载失败诊断
- **AND** 系统 MUST 记录结构化错误日志表达失败原因

#### Scenario: 文件模型 unavailable 或 skipped 时不启动预加载
- **WHEN** 文档模型文件 bootstrap 的 Docling readiness 为 `unavailable` 或 `skipped`
- **THEN** 系统 MUST NOT 启动 Docling 内存预加载任务
- **AND** Docling 内存 readiness MUST 保持与文件 bootstrap 状态兼容

### Requirement: 解析请求使用 Docling 内存 readiness
系统 SHALL 在创建或执行需要 Docling 模型的解析任务前读取 Docling 内存 readiness，并在模型仍在加载或不可用时快速返回错误状态。

#### Scenario: 预加载期间创建 PDF 解析请求
- **WHEN** 用户请求解析需要 Docling artifacts 的上传文件
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 响应 MUST 表达文档模型仍在加载中
- **AND** 系统 MUST NOT 创建会进入 Docling 懒加载路径的解析作业

#### Scenario: 预加载期间后台解析作业执行
- **WHEN** 后台解析作业需要 Docling artifacts
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** 系统 MUST 将解析作业状态更新为 `failed`
- **AND** 解析作业 `error_code` MUST 为 `model_unavailable`
- **AND** 解析作业 `error_message` MUST 表达文档模型仍在加载中
- **AND** 系统 MUST NOT 调用 Docling converter 执行懒加载

#### Scenario: 预加载完成后解析复用 converter
- **WHEN** 后台解析作业需要 Docling artifacts
- **AND** Docling 内存 readiness 为 `ready`
- **AND** readiness 中存在已初始化 converter
- **THEN** 解析适配器 MUST 使用该 converter 执行解析
- **AND** 系统 MUST NOT 为该解析作业重新初始化 Docling PDF pipeline

#### Scenario: 纯文本解析不受 Docling loading 阻塞
- **WHEN** 用户请求解析可通过项目内纯文本路径处理的上传文件
- **AND** Docling 内存 readiness 为 `loading`
- **THEN** 系统 MUST 允许创建并执行解析任务
- **AND** 系统 MUST NOT 因 Docling 内存模型仍在加载而拒绝纯文本解析

### Requirement: 健康检查暴露模型内存加载状态
系统 SHALL 复用现有 `GET /api/health` 暴露文档模型内存 readiness 摘要，并且 MUST NOT 新增独立模型健康检查 endpoint。

#### Scenario: 健康检查返回 loading 摘要
- **WHEN** 文档模型内存预加载正在进行
- **AND** 客户端调用 `GET /api/health`
- **THEN** API MUST 返回 `200`
- **AND** 响应体的 `document_models` MUST 包含整体 `loading` 状态
- **AND** 响应体 MUST 表达 Docling 或 tokenizer 的组件级 `loading` 状态
