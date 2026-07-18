# document-embedding Specification

## Purpose

定义 knowra 文档向量化能力，在现有文档解析与分块基础上，将 chunk 文本通过云端 embedding API 转化为稠密向量并持久化，为后续向量存储和语义检索提供标准化的向量输入。首版采用 OpenAI 兼容的云端 API（tumuer.me `Qwen/Qwen3-Embedding-4B`），不写入 pgvector 向量索引列，不实现语义检索。

## Requirements

### Requirement: 向量化作业模型

系统 SHALL 持久化文档向量化作业，用于追踪向量化生命周期、嵌入模型配置快照、向量数量、错误诊断和活跃结果取代。

#### Scenario: 创建向量化作业表结构

- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_embedding_jobs` 表
- **AND** `document_embedding_jobs` 表 MUST 包含 `id`、`chunk_job_id`、`parsed_document_id`、`owner_user_id`、`status`、`embedder_name`、`model`、`dimensions`、`embedding_count`、`attempt_count`、`started_at`、`finished_at`、`error_code`、`error_message`、`config_json`、`created_at`、`updated_at` 字段
- **AND** 数据库 MUST 为 `owner_user_id`、`chunk_job_id`、`parsed_document_id` 和 `status` 提供可查询索引

#### Scenario: 向量化作业状态可追踪

- **WHEN** 系统创建向量化作业
- **THEN** 向量化作业初始状态 MUST 为 `queued` 或 `running`
- **AND** 作业执行成功后状态 MUST 转换为 `succeeded`
- **AND** 作业执行失败后状态 MUST 转换为 `failed`
- **AND** 作业被新的成功向量化结果取代后状态 MUST 转换为 `superseded`
- **AND** 失败作业 MUST 保存可诊断的 `error_code` 或 `error_message`

#### Scenario: 向量化作业保存配置快照

- **WHEN** 系统创建向量化作业
- **THEN** 系统 MUST 将本次使用的 `model`、`dimensions`、`batch_size` 和 `encoding_format` 保存到 `config_json`

### Requirement: 向量结果模型

系统 SHALL 持久化每个 chunk 对应的向量结果，包括向量浮点数组、模型信息、维度和 token 消耗，以供后续向量存储、检索和来源追溯消费。

#### Scenario: 创建向量结果表结构

- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_embeddings` 表
- **AND** `document_embeddings` 表 MUST 包含 `id`、`embedding_job_id`、`chunk_id`、`parsed_document_id`、`owner_user_id`、`sequence_index`、`model`、`dimensions`、`embedding_json`、`token_count`、`created_at` 字段
- **AND** 数据库 MUST 为 `embedding_job_id`、`chunk_id`、`owner_user_id` 和 `(parsed_document_id, sequence_index)` 提供可查询索引

#### Scenario: 向量结果按 chunk 顺序保存

- **WHEN** 向量化适配器生成一个或多个向量
- **THEN** 系统 MUST 将每个向量与对应 chunk 的 `sequence_index` 关联
- **AND** 每个向量结果 MUST 关联当前向量化作业、对应 chunk 和解析文档
- **AND** 每个向量结果 MUST 保存当前用户归属以支持权限过滤

#### Scenario: 向量以 JSON 浮点数组存储

- **WHEN** 系统保存向量结果
- **THEN** `embedding_json` 字段 MUST 包含完整浮点数组（如 `[0.123, -0.456, ...]`）
- **AND** `dimensions` 字段 MUST 记录数组长度
- **AND** `model` 字段 MUST 记录生成该向量的嵌入模型名称
- **AND** `token_count` 字段 MUST 记录向量化消耗的 token 数
- **AND** 系统 MUST NOT 创建 pgvector `vector(N)` 类型列或 IVFFlat/HNSW 索引

#### Scenario: 不修改既有 chunk 或 segment 记录

- **WHEN** 系统保存向量结果
- **THEN** 系统 MUST NOT 修改、删除、合并或覆盖既有 `document_chunks` 记录
- **AND** 系统 MUST NOT 修改、删除、合并或覆盖既有 `document_segments` 记录

### Requirement: 分块成功后自动向量化

系统 SHALL 在文档分块后台任务成功后自动执行首次向量化，并在同一后台任务内将已有 chunk 文本传递给向量化服务。

#### Scenario: 分块成功后自动创建并执行向量化作业

- **WHEN** 文档分块后台任务成功生成 `document_chunks` 记录
- **AND** 向量化功能配置为启用
- **AND** 分块作业状态为 `succeeded`
- **THEN** 系统 MUST 为该分块结果创建向量化作业
- **AND** 系统 MUST 在同一后台任务中调用 `DocumentEmbeddingService.run_initial_embedding()`
- **AND** 系统 MUST 使用 chunk 的 `contextualized_text`（非空时）或 `text` 作为向量化输入
- **AND** 系统 MUST 持久化向量结果或记录向量化失败状态

#### Scenario: 向量化失败不回滚分块结果

- **WHEN** 自动向量化执行失败
- **THEN** 分块作业 MUST 保持 `succeeded`
- **AND** 解析作业 MUST 保持 `succeeded`
- **AND** 已保存的 `document_chunks` MUST 保持可查询
- **AND** 向量化作业 MUST 记录为 `failed`

#### Scenario: 向量化禁用时跳过

- **WHEN** 分块作业成功
- **AND** 向量化功能配置为禁用
- **THEN** 分块作业 MUST 保持 `succeeded`
- **AND** 系统 MUST NOT 创建向量化作业
- **AND** 系统 MUST NOT 调用嵌入模型 API

### Requirement: 云端 Embedding API 适配器

系统 SHALL 通过项目内适配器封装 OpenAI 兼容的云端 embedding API 调用，支持批量文本向量化、自动拆分超大批次、重试和超时控制，不向外暴露第三方 SDK 类型。

#### Scenario: 使用 OpenAI SDK 批量向量化

- **WHEN** 适配器收到文本列表
- **THEN** 适配器 MUST 使用 `openai` SDK 的 `client.embeddings.create()` 方法
- **AND** 调用 MUST 传递 `model`、`input`（文本数组）和可选的 `dimensions`、`encoding_format` 参数
- **AND** 适配器 MUST 返回项目内部 `EmbeddingResult` 对象列表
- **AND** 返回结果 MUST 按输入顺序排列（通过 `index` 字段匹配）

#### Scenario: 超过批大小时自动拆分

- **WHEN** 输入文本列表长度超过配置的 `batch_size`
- **THEN** 适配器 MUST 将输入拆分为多个不超过 `batch_size` 的子批次
- **AND** 适配器 MUST 对每个子批次发起独立 API 调用
- **AND** 适配器 MUST 将所有子批次结果按原始输入顺序合并返回

#### Scenario: API 调用失败时重试

- **WHEN** API 调用遇到网络超时或 5xx 错误
- **AND** 重试次数未达到 `max_retries`
- **THEN** 适配器 MUST 使用指数退避策略自动重试
- **AND** 超过 `max_retries` 后适配器 MUST 抛出项目内异常
- **AND** 异常 MUST 包含可诊断的错误信息和原始状态码

#### Scenario: API 返回格式异常时失败

- **WHEN** API 返回 2xx 但 `data` 数组长度与输入不匹配
- **OR** 返回的 `embedding` 元素维度与配置不一致
- **THEN** 适配器 MUST 抛出 `invalid_response` 错误
- **AND** 错误信息 MUST 包含期望维度和实际维度

#### Scenario: 适配器不向外暴露 OpenAI SDK 类型

- **WHEN** 适配器完成向量化
- **THEN** 服务层 MUST 接收项目内规范化的 `EmbeddingResult` 对象
- **AND** API schema、数据库模型和前端响应 MUST NOT 直接暴露 OpenAI SDK 内部对象

### Requirement: 向量化查询 API

系统 SHALL 提供向量化作业和向量结果查询 API，让当前用户查看自己文档的向量化状态与向量内容。

#### Scenario: 查询当前用户向量化作业状态

- **WHEN** 当前用户请求 `GET /api/document-embedding-jobs/{job_id}`
- **AND** 向量化作业属于当前用户
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含作业 `id`、`chunk_job_id`、`parsed_document_id`、`status`、`model`、`dimensions`、`embedding_count`、`error_code`、`error_message`、`started_at`、`finished_at`、`config_json`

#### Scenario: 分页查询分块作业的最新活跃向量结果

- **WHEN** 当前用户请求 `GET /api/document-chunk-jobs/{chunk_job_id}/embeddings`
- **AND** 分块作业属于当前用户
- **AND** 该分块作业存在最新的非 `superseded` 成功向量化作业
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 按 `sequence_index` 返回分页向量结果列表
- **AND** 响应体 MUST 包含分页信息

#### Scenario: 查询单个 chunk 的向量详情

- **WHEN** 当前用户请求 `GET /api/document-chunks/{chunk_id}/embedding`
- **AND** chunk 属于当前用户
- **AND** 该 chunk 存在成功向量结果
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含向量 `id`、`chunk_id`、`sequence_index`、`model`、`dimensions`、`embedding_json`、`token_count`

#### Scenario: 阻止读取其他用户的向量结果

- **WHEN** 当前用户请求不属于自己的向量化作业或向量结果
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST NOT 暴露其他用户的向量内容、配置快照或错误详情

### Requirement: 重新向量化 API

系统 SHALL 支持当前用户使用新的嵌入模型或维度参数重新向量化，通过读取已有 chunk 文本重新调用云端 API，无需重新解析或分块。

#### Scenario: 当前用户触发重新向量化

- **WHEN** 当前用户请求 `POST /api/document-chunk-jobs/{chunk_job_id}/re-embed`
- **AND** 分块作业属于当前用户
- **AND** 分块作业状态为 `succeeded`
- **AND** 该分块作业存在可用 chunk 记录
- **THEN** API MUST 返回 `202`
- **AND** 系统 MUST 创建状态为 `queued` 的新向量化作业
- **AND** 系统 MUST 通过 FastAPI `BackgroundTasks` 调度后台执行任务
- **AND** 后台任务 MUST 读取已有 `document_chunks` 的文本
- **AND** 后台任务 MUST 使用请求中的模型/维度参数或默认参数生成新的向量集合
- **AND** 后台任务 MUST 在新向量集合持久化完成后将新作业标记为 `succeeded` 并将被取代的旧作业标记为 `superseded`

#### Scenario: 重新向量化失败时标记作业

- **WHEN** 后台执行任务无法完成重新向量化（API 错误、网络超时等）
- **THEN** 系统 MUST 将新向量化作业标记为 `failed`
- **AND** 向量化作业 MUST 保存可诊断的 `error_code` 和 `error_message`
- **AND** 系统 MUST 保持旧 `succeeded` 向量化作业为活跃结果

#### Scenario: 重新向量化不重新解析或分块

- **WHEN** 系统执行重新向量化
- **THEN** 系统 MUST 直接使用已有 `document_chunks` 表中的文本数据
- **AND** 系统 MUST NOT 重新读取原始上传文件
- **AND** 系统 MUST NOT 重新调用解析适配器或分块适配器

#### Scenario: 运行中向量化作业阻止重复重新向量化

- **WHEN** 某分块作业已经存在 `queued` 或 `running` 的向量化作业
- **AND** 当前用户再次请求重新向量化
- **THEN** API MUST 返回 `409`
- **AND** 响应体 MUST 包含已有运行中向量化作业信息
- **AND** 系统 MUST NOT 创建新的并发向量化作业

#### Scenario: 重新向量化运行中保留旧活跃结果

- **WHEN** 某分块作业存在旧的 `succeeded` 向量化作业
- **AND** 该分块作业的新重新向量化作业处于 `queued` 或 `running`
- **THEN** 系统 MUST 保持旧向量化作业为活跃结果
- **AND** 默认向量查询 MUST 继续返回旧向量化作业的结果
- **AND** 系统 MUST NOT 在新作业成功前将旧向量化作业标记为 `superseded`

#### Scenario: 重新向量化失败保留旧活跃结果

- **WHEN** 某分块作业存在旧的 `succeeded` 向量化作业
- **AND** 该分块作业的新重新向量化作业执行失败
- **THEN** 系统 MUST 将新向量化作业标记为 `failed`
- **AND** 系统 MUST 保持旧向量化作业为活跃结果
- **AND** 默认向量查询 MUST 继续返回旧向量化作业的结果
- **AND** 系统 MUST NOT 因失败的新作业将旧向量化作业标记为 `superseded`

#### Scenario: 新结果成功后取代旧向量化作业

- **WHEN** 重新向量化作业成功生成新的向量集合
- **THEN** 系统 MUST 在新向量集合持久化完成后将被取代的旧向量化作业标记为 `superseded`
- **AND** 系统 MUST 保留旧向量结果不主动删除
- **AND** 默认向量查询 MUST 从旧向量集合切换为返回新向量化作业的结果

### Requirement: 重新向量化后台执行器

系统 SHALL 提供 `run_reembed_job` 后台执行函数，负责加载 QUEUED 向量化作业、读取已有 chunk 文本、调用 embedding API 并持久化结果。

#### Scenario: 后台执行器成功执行重新向量化

- **WHEN** `run_reembed_job` 被调度执行
- **AND** 向量化作业状态为 `queued`
- **AND** 分块作业存在且所关联的 chunks 可读取
- **AND** 进程未进入 shutdown
- **THEN** 后台执行器 MUST 将作业状态更新为 `running`
- **AND** 后台执行器 MUST 从 `document_chunks` 表读取 chunk 文本
- **AND** 后台执行器 MUST 通过 `DocumentEmbeddingService.execute_queued_job()` 执行向量化
- **AND** 作业 MUST 最终变为 `succeeded` 或 `failed`
- **AND** 成功时旧 `succeeded` 作业 MUST 被标记为 `superseded`

#### Scenario: 后台执行器因 API 错误而失败

- **WHEN** `run_reembed_job` 被调度执行
- **AND** 云端 API 调用失败（网络超时、5xx 或认证错误）
- **AND** 重试次数已耗尽
- **THEN** 后台执行器 MUST 将作业标记为 `failed`
- **AND** `error_code` MUST 为 `api_error`
- **AND** 后台执行器 MUST 记录结构化错误日志
- **AND** 后台执行器 MUST NOT 抛出未捕获异常

#### Scenario: 后台执行器因 shutdown 快速失败

- **WHEN** `run_reembed_job` 被调度执行
- **AND** 进程已进入 shutdown
- **THEN** 后台执行器 MUST 将作业标记为 `failed`
- **AND** `error_code` MUST 为 `process_shutdown`
- **AND** 后台执行器 MUST NOT 调用 embedding API

#### Scenario: 后台执行器支持依赖注入

- **WHEN** 测试代码调用 `run_reembed_job`
- **AND** 传入了 `session_factory`、`embedding_adapter` 等可选参数
- **THEN** 后台执行器 MUST 使用注入的依赖而非默认实现
- **AND** 这使得测试可以不依赖真实云端 API 和数据库连接

### Requirement: 向量化服务执行已创建作业

系统 SHALL 在 `DocumentEmbeddingService` 上提供 `execute_queued_job()` 方法，允许对 API 层已创建的 QUEUED 作业执行向量化，并始终以 `supersede_previous=True` 模式运行。

#### Scenario: 对 QUEUED 作业执行向量化

- **WHEN** 调用 `service.execute_queued_job(job=queued_job, chunks=chunks)`
- **AND** `queued_job` 状态为 `queued`
- **THEN** 方法 MUST 委托 `_run_job()` 执行完整向量化流程
- **AND** `_run_job()` MUST 以 `supersede_previous=True` 模式运行
- **AND** 成功完成后作业状态 MUST 为 `succeeded`
- **AND** 旧的 `succeeded` 作业 MUST 被标记为 `superseded`

#### Scenario: execute_queued_job 不创建新作业

- **WHEN** 调用 `service.execute_queued_job()`
- **THEN** 方法 MUST NOT 调用 `_create_job()`
- **AND** 方法 MUST 直接使用传入的 `job` 参数执行向量化

### Requirement: Embedding 配置

系统 SHALL 通过独立的 `DOCUMENT_EMBEDDING_*` 环境变量配置云端 embedding API 连接参数、向量化开关和运行参数，不复用现有 `DOCUMENT_CHUNK_*` 或 `DOCUMENT_MODEL_*` 配置。

#### Scenario: 读取默认向量化配置

- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_ENABLED`，默认值为 `true`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_API_BASE_URL`，默认值为 `https://router.tumuer.me/v1`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_API_KEY`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_MODEL`，默认值为 `Qwen/Qwen3-Embedding-4B`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_DIMENSIONS`，默认值为 `2560`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_ENCODING_FORMAT`，默认值为 `float`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_BATCH_SIZE`，默认值为 `100`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_MAX_RETRIES`，默认值为 `3`
- **AND** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_REQUEST_TIMEOUT`，默认值为 `60.0`

#### Scenario: API Key 为敏感配置

- **WHEN** 后端应用启动
- **THEN** `DOCUMENT_EMBEDDING_API_KEY` MUST 从 `.env` 文件或环境变量读取
- **AND** 系统 MUST NOT 在代码中硬编码 `DOCUMENT_EMBEDDING_API_KEY` 的值
- **AND** `.env.example` MUST 使用占位符（如 `your_api_key_here`）而非真实密钥

#### Scenario: 配置独立不复用

- **WHEN** `DOCUMENT_EMBEDDING_*` 变量未显式配置
- **AND** 既有 `DOCUMENT_CHUNK_*` 或 `DOCUMENT_MODEL_*` 变量已配置为非默认值
- **THEN** Embedding 配置 MUST 使用 `DOCUMENT_EMBEDDING_*` 默认值或显式配置值
- **AND** 系统 MUST NOT 使用任何既有分块或模型变量作为 embedding 配置的 fallback

### Requirement: 前端向量化状态体验

前端 SHALL 在分块完成后展示向量化状态、错误反馈、向量预览入口和重新向量化入口，但不得将向量化完成表述为已经完成检索或 RAG。

#### Scenario: 展示向量化中状态

- **WHEN** 分块作业成功且向量化作业状态为 `queued` 或 `running`
- **THEN** 前端 MUST 展示向量化中反馈
- **AND** 前端 MUST 防止用户重复触发重新向量化

#### Scenario: 展示向量化完成和预览入口

- **WHEN** 向量化作业状态为 `succeeded`
- **THEN** 前端 MUST 展示向量化完成反馈
- **AND** 前端 MUST 提供查看向量预览的入口
- **AND** 前端 MUST NOT 表示该文档已经完成语义检索或 RAG 问答准备

#### Scenario: 展示向量化失败和重新向量化入口

- **WHEN** 向量化作业状态为 `failed`
- **THEN** 前端 MUST 展示用户可理解的错误反馈
- **AND** 前端 MUST 保留通过重新向量化触发完整重试的入口

#### Scenario: 展示向量化未开始或禁用状态

- **WHEN** 向量化功能被禁用或尚未触发
- **THEN** 前端 MUST 展示"暂未向量化"状态
- **AND** 前端 MUST NOT 展示可触发向量化的入口（当功能禁用时）

### Requirement: 首版向量化范围边界

系统 SHALL 将首版文档向量化限定为生成并持久化 chunk 向量，不在本能力中实现 pgvector 索引写入、语义检索或 RAG。

#### Scenario: 向量化完成后不创建向量索引

- **WHEN** 向量化作业状态变为 `succeeded`
- **THEN** 系统 MUST NOT 在本变更中创建 pgvector 向量类型列
- **AND** 系统 MUST NOT 创建 IVFFlat 或 HNSW 索引
- **AND** 系统 MUST NOT 启用语义检索或 RAG 问答能力

### Requirement: 向量化作业关闭收尾

系统 SHALL 在 graceful shutdown 期间对无法继续完成的文档向量化作业写入明确失败状态，避免作业永久残留在 `queued` 或 `running`。

#### Scenario: 关闭时标记 queued 向量化作业失败

- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `queued` 的文档向量化作业
- **THEN** 系统 MUST 将该向量化作业状态更新为 `failed`
- **AND** 向量化作业 `error_code` MUST 为 `process_shutdown`
- **AND** 向量化作业 `error_message` MUST 表达进程关闭导致作业未完成
- **AND** 向量化作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 关闭时标记 running 向量化作业失败

- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `running` 的文档向量化作业
- **THEN** 系统 MUST 将该向量化作业状态更新为 `failed`
- **AND** 向量化作业 `error_code` MUST 为 `process_shutdown`
- **AND** 向量化作业 `error_message` MUST 表达进程关闭导致作业中断
- **AND** 向量化作业 MUST 写入 `finished_at` 和更新 `updated_at`

#### Scenario: 不覆盖已完成向量化作业

- **WHEN** graceful shutdown 开始
- **AND** 文档向量化作业状态为 `succeeded`、`failed` 或 `superseded`
- **THEN** 系统 MUST NOT 修改该向量化作业的状态、错误码或完成时间

### Requirement: 向量化执行路径协作式响应关闭

系统 SHALL 在重新向量化请求创建和向量化执行关键边界检查应用关闭状态，并在关闭期快速失败。

#### Scenario: 关闭期拒绝创建重新向量化作业

- **WHEN** 应用已进入 graceful shutdown
- **AND** 用户请求重新向量化
- **THEN** API MUST 返回 `503 Service Unavailable`
- **AND** 系统 MUST NOT 创建新的文档向量化作业
- **AND** 响应 MUST 表达服务正在关闭

#### Scenario: 向量化作业进入 API 调用前发现关闭

- **WHEN** 向量化作业准备调用云端 embedding API
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将向量化作业状态更新为 `failed`
- **AND** 向量化作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 调用云端 embedding API

#### Scenario: 向量化作业写入成功前发现关闭

- **WHEN** 向量化作业已获得 API 响应但尚未写入成功状态
- **AND** 应用已进入 graceful shutdown
- **THEN** 系统 MUST 将向量化作业状态更新为 `failed`
- **AND** 向量化作业 `error_code` MUST 为 `process_shutdown`
- **AND** 系统 MUST NOT 将该向量化作业标记为 `succeeded`
