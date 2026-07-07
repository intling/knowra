# document-chunking Specification

## Purpose
TBD - created by archiving change add-document-chunking-docling. Update Purpose after archive.
## Requirements
### Requirement: 文档分块作业模型
系统 SHALL 持久化文档分块作业，用于追踪分块生命周期、配置快照、分块器版本、错误诊断和分块结果数量。

#### Scenario: 创建分块作业表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_chunk_jobs` 表
- **AND** `document_chunk_jobs` 表 MUST 包含 `id`、`parsed_document_id`、`owner_user_id`、`status`、`chunker_name`、`chunker_version`、`chunk_config_json`、`chunk_count`、`attempt_count`、`started_at`、`finished_at`、`error_code`、`error_message`、`created_at`、`updated_at` 字段
- **AND** 数据库 MUST 为 `owner_user_id`、`parsed_document_id` 和 `status` 提供可查询索引

#### Scenario: 分块作业状态可追踪
- **WHEN** 系统创建分块作业
- **THEN** 分块作业初始状态 MUST 为 `queued` 或 `running`
- **AND** 作业执行成功后状态 MUST 转换为 `succeeded`
- **AND** 作业执行失败后状态 MUST 转换为 `failed`
- **AND** 作业被新的成功重新分块结果取代后状态 MUST 转换为 `superseded`
- **AND** 失败作业 MUST 保存可诊断的 `error_code` 或 `error_message`

### Requirement: 解析成功后自动分块
系统 SHALL 在文档解析后台任务成功后自动执行首次分块，并在同一后台任务内将内存中的 `DoclingDocument` 直接传递给分块适配器。

#### Scenario: 解析成功后自动创建并执行分块作业
- **WHEN** 文档解析后台任务成功生成 `parsed_documents` 记录
- **AND** 分块功能配置为启用
- **AND** 解析运行仍持有 transient `DoclingDocument`
- **THEN** 系统 MUST 为该解析结果创建分块作业
- **AND** 系统 MUST 在同一后台任务中把该 transient `DoclingDocument` 传递给分块适配器
- **AND** 系统 MUST 持久化分块结果或记录分块失败状态

#### Scenario: 缺少 transient DoclingDocument 时分块失败
- **WHEN** 文档解析后台任务成功生成可持久化解析产物
- **AND** 解析内部结果不包含 transient `DoclingDocument`
- **THEN** 系统 MUST 将对应分块作业标记为 `failed`
- **AND** 错误信息 MUST 表达解析适配器未提供可用于原生分块的内存文档对象
- **AND** 系统 MUST NOT 从 `docling.json`、pickle 或其他已落地解析产物还原 `DoclingDocument` 后继续分块

#### Scenario: 不提供独立首次分块 API
- **WHEN** 客户端尝试在解析成功后通过独立首次 `POST /chunk` 入口启动分块
- **THEN** 系统 MUST NOT 提供该入口作为首版公共 API
- **AND** 首次分块 MUST 由解析流程自动触发

### Requirement: Docling HybridChunker 分块适配
系统 SHALL 通过项目内分块适配器封装 Docling `HybridChunker`，从内存 `DoclingDocument` 生成 token 感知且包含结构元数据的 chunk。

#### Scenario: 使用默认 HybridChunker 配置生成 chunk
- **WHEN** 分块适配器接收到内存中的 `DoclingDocument`
- **THEN** 适配器 MUST 使用 Docling `HybridChunker` 执行分块
- **AND** 默认 tokenizer 模型 MUST 为 `Qwen/Qwen2-7B`
- **AND** 默认最大 token 数 MUST 为 `512`
- **AND** 默认 `merge_peers` MUST 为 `true`
- **AND** 适配器 MUST 为每个 chunk 生成原始文本和 contextualized 文本

#### Scenario: 分块适配器不向外暴露 Docling SDK 类型
- **WHEN** 分块适配器完成分块
- **THEN** 服务层 MUST 接收项目内规范化 chunk 结果
- **AND** API schema、数据库模型和前端响应 MUST NOT 直接暴露 Docling SDK 内部对象

### Requirement: 分块结果模型
系统 SHALL 持久化每个文档 chunk 的文本、上下文文本、顺序、token 计数、结构位置和来源追溯信息，以供后续 embedding、检索和引用定位消费。

#### Scenario: 创建分块结果表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_chunks` 表
- **AND** `document_chunks` 表 MUST 包含 `id`、`chunk_job_id`、`parsed_document_id`、`owner_user_id`、`sequence_index`、`text`、`text_storage_key`、`contextualized_text`、`contextualized_text_storage_key`、`token_count`、`heading_path`、`page_numbers`、`chunk_type`、`source_segment_indices`、`metadata_json`、`created_at` 字段
- **AND** 数据库 MUST 为 `chunk_job_id`、`parsed_document_id`、`owner_user_id` 和 `(parsed_document_id, sequence_index)` 提供可查询索引

#### Scenario: 分块结果按文档顺序保存
- **WHEN** 分块适配器生成一个或多个 chunk
- **THEN** 系统 MUST 从 `0` 开始为 chunk 分配稳定递增的 `sequence_index`
- **AND** 每个 chunk MUST 关联当前分块作业和解析结果
- **AND** 每个 chunk MUST 保存当前用户归属以支持权限过滤

#### Scenario: 分块不修改解析结构片段
- **WHEN** 系统保存 chunk 结果
- **THEN** 系统 MUST NOT 修改、删除、合并或覆盖既有 `document_segments` 记录
- **AND** 当 chunk 与 segment 来自同一次解析运行且映射可靠时，系统 MAY 在 `source_segment_indices` 保存来源 segment 序号
- **AND** 当映射不可靠时，`source_segment_indices` MUST 保持为空或缺省

### Requirement: 分块文本阈值混合存储
系统 SHALL 对 chunk 原始文本和 contextualized 文本分别采用阈值混合存储，避免大文本无限膨胀数据库。

#### Scenario: 短文本直接入库
- **WHEN** chunk 的 `text` 或 `contextualized_text` 内容小于或等于配置的入库阈值
- **THEN** 系统 MUST 将该内容保存到对应数据库文本字段
- **AND** 对应 `*_storage_key` 字段 MUST 为空

#### Scenario: 长文本写入文件存储
- **WHEN** chunk 的 `text` 或 `contextualized_text` 内容大于配置的入库阈值
- **THEN** 系统 MUST 将该内容写入分块产物文件存储
- **AND** 系统 MUST 将对应 storage key 保存到数据库
- **AND** 对应数据库文本字段 MUST 为空

### Requirement: 分块查询 API
系统 SHALL 提供分块作业和分块结果查询 API，让当前用户查看自己文档的分块状态与 chunk 内容。

#### Scenario: 查询当前用户分块作业状态
- **WHEN** 当前用户请求 `GET /api/document-chunk-jobs/{job_id}`
- **AND** 分块作业属于当前用户
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含作业 `id`、`parsed_document_id`、`status`、`chunk_config_json`、`chunk_count`、`error_code`、`error_message`、`started_at`、`finished_at`

#### Scenario: 分页查询解析结果的最新活跃 chunks
- **WHEN** 当前用户请求 `GET /api/parsed-documents/{parsed_document_id}/chunks`
- **AND** 解析结果属于当前用户
- **AND** 该解析结果存在最新的非 `superseded` 成功分块作业
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 按 `sequence_index` 返回分页 chunk 列表
- **AND** 响应体 MUST 包含分页信息

#### Scenario: 查询单个 chunk 详情
- **WHEN** 当前用户请求 `GET /api/document-chunks/{chunk_id}`
- **AND** chunk 属于当前用户
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含 chunk 文本、contextualized 文本、token 计数、标题路径、页码、来源 segment 索引和元数据

#### Scenario: 阻止读取其他用户的分块结果
- **WHEN** 当前用户请求不属于自己的分块作业或 chunk
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST NOT 暴露其他用户的分块内容、配置快照或错误详情

### Requirement: 重新分块 API
系统 SHALL 支持当前用户使用新的分块参数重新分块，并通过重新读取原始上传文件和重新解析来获得新的内存 `DoclingDocument`。

#### Scenario: 当前用户触发重新分块
- **WHEN** 当前用户请求 `POST /api/parsed-documents/{parsed_document_id}/rechunk`
- **AND** 解析结果属于当前用户
- **AND** 原始上传文件仍可读取
- **THEN** API MUST 返回 `202`
- **AND** 系统 MUST 创建新的分块作业
- **AND** 系统 MUST 重新读取原始上传文件并重新解析以获得新的内存 `DoclingDocument`
- **AND** 系统 MUST 使用请求中的分块参数或默认参数生成新的 chunk 集合

#### Scenario: 重新分块不读取旧 docling.json
- **WHEN** 系统执行重新分块
- **THEN** 系统 MUST NOT 读取旧 `docling.json` 作为 `DoclingDocument` 还原输入
- **AND** 系统 MUST NOT 从 pickle 或其他已落地解析产物还原 `DoclingDocument`

#### Scenario: 运行中分块作业阻止重复重新分块
- **WHEN** 某解析结果已经存在 `queued` 或 `running` 的分块作业
- **AND** 当前用户再次请求重新分块
- **THEN** API MUST 返回 `409`
- **AND** 响应体 MUST 包含已有运行中分块作业信息
- **AND** 系统 MUST NOT 创建新的并发分块作业

#### Scenario: 重新分块运行中保留旧活跃结果
- **WHEN** 某解析结果存在旧的 `succeeded` 分块作业
- **AND** 该解析结果的新重新分块作业处于 `queued` 或 `running`
- **THEN** 系统 MUST 保持旧分块作业为活跃结果
- **AND** 默认 chunk 查询 MUST 继续返回旧分块作业的 chunk
- **AND** 系统 MUST NOT 在新作业成功前将旧分块作业标记为 `superseded`

#### Scenario: 重新分块失败保留旧活跃结果
- **WHEN** 某解析结果存在旧的 `succeeded` 分块作业
- **AND** 该解析结果的新重新分块作业执行失败
- **THEN** 系统 MUST 将新分块作业标记为 `failed`
- **AND** 系统 MUST 保持旧分块作业为活跃结果
- **AND** 默认 chunk 查询 MUST 继续返回旧分块作业的 chunk
- **AND** 系统 MUST NOT 因失败的新作业将旧分块作业标记为 `superseded`

#### Scenario: 新结果成功后取代旧分块作业
- **WHEN** 重新分块作业成功生成新的 chunk 集合
- **THEN** 系统 MUST 在新 chunk 集合持久化完成后将被取代的旧分块作业标记为 `superseded`
- **AND** 系统 MUST 保留旧 chunk 结果不主动删除
- **AND** 默认 chunk 查询 MUST 从旧 chunk 集合切换为返回新分块作业的 chunk

#### Scenario: 原始上传文件不可用时拒绝重新分块
- **WHEN** 当前用户请求重新分块
- **AND** 原始上传文件已删除或不可读取
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 从旧解析产物还原文档对象来替代重新解析

### Requirement: 分块配置
系统 SHALL 通过配置管理分块开关、tokenizer、token 上限、合并行为、表头重复行为、文本入库阈值和分块产物目录。

#### Scenario: 读取默认分块配置
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取分块启用开关
- **AND** 默认最大 token 数 MUST 为 `512`
- **AND** 默认 tokenizer 模型 MUST 为 `Qwen/Qwen2-7B`
- **AND** 默认文本入库阈值 MUST 为 `2048` 字节
- **AND** 默认分块产物目录 MUST 可通过环境变量覆盖

#### Scenario: 分块配置快照随作业持久化
- **WHEN** 系统创建分块作业
- **THEN** 系统 MUST 将本次使用的 max_tokens、tokenizer_model、merge_peers、repeat_table_header 和文本入库阈值保存到 `chunk_config_json`

### Requirement: 前端分块状态体验
前端 SHALL 在解析完成后展示分块状态、错误反馈、chunk 预览入口和重新分块入口，但不得将分块完成表述为已经完成检索或 RAG。

#### Scenario: 展示分块中状态
- **WHEN** 解析作业成功且分块作业状态为 `queued` 或 `running`
- **THEN** 前端 MUST 展示分块中反馈
- **AND** 前端 MUST 防止用户重复触发重新分块

#### Scenario: 展示分块完成和预览入口
- **WHEN** 分块作业状态为 `succeeded`
- **THEN** 前端 MUST 展示分块完成反馈
- **AND** 前端 MUST 提供查看 chunk 结果预览的入口
- **AND** 前端 MUST NOT 表示该文档已经完成 embedding、语义检索或 RAG 问答准备

#### Scenario: 展示分块失败和重新分块入口
- **WHEN** 分块作业状态为 `failed`
- **THEN** 前端 MUST 展示用户可理解的错误反馈
- **AND** 前端 MUST 保留通过重新分块触发完整重试的入口

### Requirement: 首版分块范围边界
系统 SHALL 将首版文档分块限定为生成可追溯 chunk，不在本能力中实现 embedding、向量索引、语义检索或 RAG。

#### Scenario: 分块完成后不创建向量索引
- **WHEN** 分块作业状态变为 `succeeded`
- **THEN** 系统 MUST NOT 在本变更中创建 embedding 记录
- **AND** 系统 MUST NOT 写入 pgvector chunk 索引
- **AND** 系统 MUST NOT 启用语义检索或 RAG 问答能力

### Requirement: 分块 tokenizer 启动准备
系统 SHALL 将默认分块 tokenizer 纳入启动模型 bootstrap，并通过独立的 `DOCUMENT_MODEL_*` 变量声明 tokenizer 名称和缓存目录。

#### Scenario: 默认 tokenizer 已缓存时启动为 ready
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中已存在 `DOCUMENT_MODEL_TOKENIZER_NAME` 对应的 tokenizer 文件
- **THEN** 模型 bootstrap MUST 将 tokenizer readiness 标记为 `ready`
- **AND** 系统 MUST 记录结构化日志表达 tokenizer 已可用

#### Scenario: check_only 策略发现 tokenizer 缺失
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `check_only`
- **AND** `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer 未在 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中可用
- **THEN** 模型 bootstrap MUST NOT 尝试下载 tokenizer
- **AND** 模型 bootstrap MUST 将 tokenizer readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含缺失的 tokenizer 名称

#### Scenario: download_missing 策略下载 tokenizer
- **WHEN** `DOCUMENT_MODEL_BOOTSTRAP_ENABLED` 为 `true`
- **AND** `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY` 为 `download_missing`
- **AND** `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer 未在 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 中可用
- **THEN** 模型 bootstrap MUST 将 tokenizer 下载到 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`
- **AND** 下载完成后系统 MUST 重新检查 tokenizer 可用性
- **AND** tokenizer 可用时 readiness MUST 标记为 `ready`

#### Scenario: tokenizer 准备不复用分块配置变量
- **WHEN** `DOCUMENT_MODEL_TOKENIZER_NAME` 未显式配置
- **AND** `DOCUMENT_CHUNK_TOKENIZER_MODEL` 已配置为非默认值
- **THEN** 模型 bootstrap MUST 使用 `DOCUMENT_MODEL_TOKENIZER_NAME` 的默认值或显式配置值
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_CHUNK_TOKENIZER_MODEL` 作为 tokenizer 准备目标
- **AND** 模型 bootstrap MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 tokenizer cache 目录 fallback

### Requirement: 分块任务使用 tokenizer readiness
系统 SHALL 在自动分块和重新分块执行前读取 tokenizer readiness，并在 tokenizer 不可用时产生明确的模型不可用错误。

#### Scenario: tokenizer ready 时使用启动准备缓存
- **WHEN** 分块作业使用 `DOCUMENT_MODEL_TOKENIZER_NAME` 对应 tokenizer
- **AND** tokenizer readiness 为 `ready`
- **THEN** 分块适配器 MUST 使用 `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` 作为 tokenizer cache 目录
- **AND** 分块适配器 MUST NOT 使用 `DOCUMENT_PARSE_DOCLING_CACHE_DIR` 作为 tokenizer cache 目录

#### Scenario: tokenizer unavailable 时分块作业失败为模型不可用
- **WHEN** 分块作业需要 tokenizer
- **AND** tokenizer readiness 为 `unavailable`
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `model_unavailable`
- **AND** 分块作业 `error_message` MUST 包含缺失 tokenizer 或模型准备失败原因
- **AND** 系统 MUST NOT 在该分块作业内触发 Transformers 或 Hugging Face 的隐式网络下载

#### Scenario: 重新分块请求使用未准备 tokenizer
- **WHEN** 当前用户请求重新分块
- **AND** 请求中的 tokenizer 与 `DOCUMENT_MODEL_TOKENIZER_NAME` 不一致
- **THEN** 系统 MUST 拒绝使用未准备 tokenizer 执行分块
- **AND** API 或分块作业错误 MUST 表达该 tokenizer 不在启动准备范围内
- **AND** 系统 MUST NOT 在请求路径中临时下载未准备 tokenizer

### Requirement: 分块 tokenizer 内存异步预加载
系统 SHALL 在文档模型文件 bootstrap ready 后异步加载默认分块 tokenizer 到进程内存，并且 MUST NOT 因 tokenizer 内存预加载阻塞 FastAPI 应用启动完成。

#### Scenario: tokenizer 文件 ready 后进入异步加载状态
- **WHEN** 后端启动阶段完成文档模型文件 bootstrap
- **AND** tokenizer 文件 readiness 为 `ready`
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `loading`
- **AND** 系统 MUST 启动后台任务加载 tokenizer
- **AND** FastAPI 应用启动 MUST NOT 等待该后台任务完成

#### Scenario: tokenizer 内存加载成功
- **WHEN** tokenizer 后台预加载任务成功创建分块 tokenizer
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `ready`
- **AND** 系统 MUST 保留已创建 tokenizer 供后续分块复用
- **AND** 系统 MUST 记录结构化日志表达 tokenizer 已加载到内存

#### Scenario: tokenizer 内存加载失败
- **WHEN** tokenizer 后台预加载任务失败
- **THEN** 系统 MUST 将 tokenizer 内存 readiness 标记为 `unavailable`
- **AND** readiness 结果 MUST 包含加载失败诊断
- **AND** 系统 MUST 记录结构化错误日志表达失败原因

### Requirement: 分块任务使用 tokenizer 内存 readiness
系统 SHALL 在自动分块和重新分块执行前读取 tokenizer 内存 readiness，并在 tokenizer 仍在加载或不可用时快速返回错误状态。

#### Scenario: 预加载期间自动分块执行
- **WHEN** 自动分块作业需要 tokenizer
- **AND** tokenizer 内存 readiness 为 `loading`
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `model_unavailable`
- **AND** 分块作业 `error_message` MUST 表达 tokenizer 仍在加载中
- **AND** 系统 MUST NOT 在该分块作业内触发 tokenizer 懒加载

#### Scenario: 预加载期间请求重新分块
- **WHEN** 用户请求重新分块
- **AND** tokenizer 内存 readiness 为 `loading`
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 响应 MUST 表达 tokenizer 仍在加载中
- **AND** 系统 MUST NOT 创建新的重新分块作业

#### Scenario: 预加载完成后分块复用 tokenizer
- **WHEN** 分块作业需要 tokenizer
- **AND** tokenizer 内存 readiness 为 `ready`
- **AND** readiness 中存在已创建 tokenizer
- **THEN** 分块适配器 MUST 使用该 tokenizer 执行分块
- **AND** 系统 MUST NOT 为该分块作业重新加载 tokenizer

### Requirement: 分块作业关闭收尾
系统 SHALL 在 graceful shutdown 期间对无法继续完成的文档分块作业写入明确失败状态，避免作业永久残留在 `queued` 或 `running`。

#### Scenario: 关闭时标记 queued 分块作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `queued` 的文档分块作业
- **THEN** 系统 MUST 将该分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 分块作业 `error_message` MUST 表达进程关闭导致作业未完成
- **AND** 分块作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 关闭时标记 running 分块作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `running` 的文档分块作业
- **THEN** 系统 MUST 将该分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 分块作业 `error_message` MUST 表达进程关闭导致作业中断
- **AND** 分块作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 不覆盖已完成分块作业
- **WHEN** graceful shutdown 开始
- **AND** 文档分块作业状态为 `succeeded`、`failed` 或 `superseded`
- **THEN** 系统 MUST NOT 修改该分块作业的状态、错误码或完成时间

### Requirement: 分块执行路径协作式响应关闭
系统 SHALL 在重新分块请求创建和分块执行关键边界检查应用关闭状态，并在关闭期快速失败。

#### Scenario: 关闭期拒绝创建重新分块作业
- **WHEN** 应用已进入 graceful shutdown
- **AND** 用户请求重新分块
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 系统 MUST NOT 创建新的文档分块作业
- **AND** 响应 MUST 表达服务正在关闭

#### Scenario: 分块作业进入 tokenizer 调用前发现关闭
- **WHEN** 分块作业准备调用 tokenizer 或 Docling HybridChunker
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 调用 tokenizer 或 Docling HybridChunker

#### Scenario: 分块作业写入成功前发现关闭
- **WHEN** 分块作业已生成 chunk 但尚未写入成功状态
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将分块作业状态更新为 `failed`
- **AND** 分块作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 将该分块作业标记为 `succeeded`

