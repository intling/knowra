# document-embedding Specification

## Purpose
本能力定义了文档向量化的完整行为：将分块后的文本块通过 OpenAI 兼容的云端 Embedding API 转化为语义向量，存储到 pgvector 向量数据库，为后续语义检索和 RAG 问答提供基础。

## ADDED Requirements

### Requirement: 向量化作业模型
系统 SHALL 持久化向量化作业，用于追踪向量化生命周期、模型配置、维度、错误诊断和向量化结果数量。

#### Scenario: 创建向量化作业表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_embedding_jobs` 表
- **AND** `document_embedding_jobs` 表 MUST 包含 `id`、`chunk_job_id`、`parsed_document_id`、`owner_user_id`、`status`、`embedder_name`、`embedder_version`、`embedding_dim`、`embed_config_json`、`chunk_count`、`attempt_count`、`started_at`、`finished_at`、`error_code`、`error_message`、`created_at`、`updated_at` 字段
- **AND** 数据库 MUST 为 `chunk_job_id`、`parsed_document_id`、`owner_user_id` 和 `status` 提供可查询索引

#### Scenario: 向量化作业状态可追踪
- **WHEN** 系统创建向量化作业
- **THEN** 向量化作业初始状态 MUST 为 `queued` 或 `running`
- **AND** 作业执行成功后状态 MUST 转换为 `succeeded`
- **AND** 作业执行失败后状态 MUST 转换为 `failed`
- **AND** 作业被新的成功向量化结果取代后状态 MUST 转换为 `superseded`
- **AND** 失败作业 MUST 保存可诊断的 `error_code` 和 `error_message`
- **AND** 作业 MUST 保存 `embed_config_json` 配置快照供审计

### Requirement: 向量存储模型
系统 SHALL 将每个 chunk 的语义向量持久化到独立的向量存储表，关联 chunk 和向量化作业，并为查询和权限过滤提供索引。

#### Scenario: 创建向量存储表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_chunk_embeddings` 表
- **AND** `document_chunk_embeddings` 表 MUST 包含 `id`、`chunk_id`、`embedding_job_id`、`owner_user_id`、`embedding`、`sequence_index`、`created_at` 字段
- **AND** `embedding` 列 MUST 使用 pgvector `vector(1024)` 类型
- **AND** 数据库 MUST 为 `chunk_id`、`embedding_job_id` 和 `owner_user_id` 提供可查询索引

#### Scenario: 向量按文档顺序存储
- **WHEN** 系统为一批 chunk 写入向量
- **THEN** 每个向量 MUST 关联对应 chunk 的 `chunk_id`
- **AND** 每个向量 MUST 冗余 chunk 的 `sequence_index` 便于按文档顺序返回检索结果
- **AND** 每个向量 MUST 关联当前向量化作业 `embedding_job_id`
- **AND** 每个向量 MUST 保存 `owner_user_id` 以支持权限过滤

#### Scenario: 不修改 chunk 表结构
- **WHEN** 系统创建向量存储表
- **THEN** 系统 MUST NOT 修改 `document_chunks` 表的列结构
- **AND** 系统 MUST NOT 在 `document_chunks` 表上新增向量列

### Requirement: OpenAI 兼容 Embedding 适配器
系统 SHALL 通过 OpenAI 兼容适配器封装云端 Embedding API 调用，支持通过配置切换不同的 Embedding 服务商，并将第三方 API 类型隔离在适配器内部。

#### Scenario: 批量调用 Embedding API 生成向量
- **WHEN** 适配器收到文本列表 `["text1", "text2", ..., "textN"]`
- **THEN** 适配器 MUST 向 `{base_url}/v1/embeddings` 发送 POST 请求
- **AND** 请求体 MUST 包含 `model`、`input` 和 `dimensions` 参数
- **AND** 适配器 MUST 按 `batch_size` 分片发送，每批不超过配置的 batch 大小
- **AND** 适配器 MUST 返回与输入文本等长的向量列表

#### Scenario: 支持透传 provider 特有参数
- **WHEN** 适配器初始化时接收到 `extra_body` 参数（如 `{"text_type": "document"}`）
- **THEN** 适配器 MUST 将 `extra_body` 合并到每次 API 请求的 JSON body 中
- **AND** 调用方不需要感知特定 provider 的参数差异

#### Scenario: 适配器不暴露第三方 API 类型
- **WHEN** 适配器完成向量生成
- **THEN** 服务层 MUST 接收项目内规范的 `list[list[float]]` 向量结果
- **AND** API schema、数据库模型和前端响应 MUST NOT 直接暴露第三方 SDK 或 HTTP 响应结构

#### Scenario: 探测并校验向量维度
- **WHEN** 适配器首次调用 Embedding API
- **AND** 返回的向量维度与配置的 `dimensions` 不一致
- **THEN** 适配器 MUST 抛出 `EmbeddingDimensionError`
- **AND** 系统 MUST NOT 将维度不匹配的向量写入数据库

### Requirement: 错误处理与重试
系统 SHALL 对 Embedding API 调用中的各类错误进行分类处理，提供可诊断的错误信息，并确保向量化作业的原子性。

#### Scenario: API Key 无效时快速失败
- **WHEN** Embedding API 返回 401 Unauthorized
- **THEN** 适配器 MUST NOT 重试
- **AND** 向量化作业 MUST 标记为 `failed`
- **AND** `error_code` MUST 为 `unauthorized`

#### Scenario: 模型不存在时快速失败
- **WHEN** Embedding API 返回 404 Not Found
- **THEN** 适配器 MUST NOT 重试
- **AND** 向量化作业 MUST 标记为 `failed`
- **AND** `error_code` MUST 为 `model_not_found`

#### Scenario: 服务不可达时重试
- **WHEN** Embedding API 连接失败（ConnectionError）
- **THEN** 适配器 MUST 重试最多 3 次（指数退避）
- **AND** 所有重试失败后向量化作业 MUST 标记为 `failed`
- **AND** `error_code` MUST 为 `service_unreachable`

#### Scenario: 请求超时时重试
- **WHEN** Embedding API 请求超时
- **THEN** 适配器 MUST 重试 1 次
- **AND** 重试仍失败后向量化作业 MUST 标记为 `failed`
- **AND** `error_code` MUST 为 `request_timeout`

#### Scenario: 向量化作业原子性
- **WHEN** 向量化过程中任意 batch 请求失败
- **THEN** 系统 MUST NOT 部分写入已成功生成的向量
- **AND** 向量化作业 MUST 整体标记为 `failed`
- **AND** 系统 MUST 记录结构化错误日志，包含失败 batch 的索引和错误原因

### Requirement: 分块成功后自动向量化
系统 SHALL 在分块作业成功后，在同一后台任务中自动从已持久化的 chunk 记录读取文本并调用 Embedding 适配器生成向量。

#### Scenario: 分块成功后创建并执行向量化作业
- **WHEN** 分块作业状态变为 `succeeded`
- **AND** 向量化功能配置为启用（`DOCUMENT_EMBEDDING_ENABLED=true`）
- **THEN** 系统 MUST 自动创建向量化作业
- **AND** 系统 MUST 在同一后台任务中从 `document_chunks` 读取每条 chunk 的 `contextualized_text`
- **AND** 系统 MUST 调用 Embedding 适配器生成向量
- **AND** 系统 MUST 将向量逐条写入 `document_chunk_embeddings` 表
- **AND** 向量化作业 MUST 最终变为 `succeeded` 或 `failed`

#### Scenario: 向量化失败不影响分块结果
- **WHEN** 分块成功后的自动向量化执行失败
- **THEN** 系统 MUST 将向量化作业标记为 `failed`
- **AND** 系统 MUST 保持分块作业为 `succeeded`
- **AND** 分块结果（chunks）MUST 仍可正常查询和使用
- **AND** 系统 MUST 记录结构化错误日志

#### Scenario: 向量化被禁用时跳过
- **WHEN** `DOCUMENT_EMBEDDING_ENABLED` 为 `false`
- **THEN** 系统 MUST NOT 创建向量化作业
- **AND** 系统 MUST NOT 调用 Embedding API
- **AND** 分块流程 MUST 正常完成不受影响

#### Scenario: 不提供独立首次向量化 API
- **WHEN** 客户端尝试通过独立 `POST /embed` 入口启动首次向量化
- **THEN** 系统 MUST NOT 提供该入口
- **AND** 首次向量化 MUST 由分块流程自动触发

### Requirement: 重新分块成功后自动重新向量化
系统 SHALL 在重新分块（`/rechunk`）成功后自动触发新分块结果的向量化，并将旧向量化作业标记为 `superseded`。

#### Scenario: 重新分块成功后自动向量化并取代旧结果
- **WHEN** 重新分块作业状态变为 `succeeded`
- **AND** 向量化功能配置为启用
- **THEN** 系统 MUST 自动创建新的向量化作业
- **AND** 系统 MUST 从新分块结果读取 chunk 文本生成向量
- **AND** 新向量化作业成功后，旧的 `succeeded` 向量化作业 MUST 被标记为 `superseded`
- **AND** 旧向量数据 MUST 保留不主动删除
- **AND** 默认向量查询 MUST 返回新向量化作业的结果

#### Scenario: 重新分块失败时不触发向量化
- **WHEN** 重新分块作业执行失败
- **THEN** 系统 MUST NOT 创建向量化作业
- **AND** 系统 MUST NOT 修改旧向量化作业的状态

### Requirement: 独立重新向量化 API
系统 SHALL 提供 `POST /api/parsed-documents/{parsed_document_id}/reembed` API，支持用户在分块结果不变的情况下使用新参数重新生成向量。

#### Scenario: 当前用户触发重新向量化
- **WHEN** 当前用户请求 `POST /api/parsed-documents/{parsed_document_id}/reembed`
- **AND** 解析结果属于当前用户
- **AND** 存在活跃的（非 `superseded`）成功分块作业
- **AND** 不存在 `queued` 或 `running` 的向量化作业
- **THEN** API MUST 返回 `202`
- **AND** 系统 MUST 创建状态为 `queued` 的新向量化作业
- **AND** 系统 MUST 通过 FastAPI `BackgroundTasks` 调度后台执行
- **AND** 后台任务 MUST 从活跃分块作业的 chunks 读取文本
- **AND** 后台任务 MUST 使用请求中的参数或默认配置生成向量
- **AND** 新向量化作业成功后旧作业 MUST 被标记为 `superseded`

#### Scenario: 请求中可覆盖模型参数
- **WHEN** 当前用户请求 `POST /api/parsed-documents/{parsed_document_id}/reembed`
- **AND** 请求体包含 `embedder_name` 或 `embedding_dim`
- **THEN** 系统 MUST 使用请求中的参数创建向量化作业
- **AND** 系统 MUST 将请求参数写入 `embed_config_json`
- **AND** 请求参数 MUST 与当前 pgvector 列维度一致，否则 API 返回 `422`

#### Scenario: 无可用分块结果时拒绝重新向量化
- **WHEN** 当前用户请求重新向量化
- **AND** 该解析结果不存在活跃的成功分块作业
- **THEN** API MUST 返回 `412 Precondition Failed`
- **AND** 响应 MUST 表达无可用的分块结果

#### Scenario: 运行中向量化作业阻止重复请求
- **WHEN** 某解析结果已存在 `queued` 或 `running` 的向量化作业
- **AND** 当前用户再次请求重新向量化
- **THEN** API MUST 返回 `409 Conflict`
- **AND** 响应体 MUST 包含已有运行中向量化作业的信息
- **AND** 系统 MUST NOT 创建新的并发向量化作业

### Requirement: 向量化查询 API
系统 SHALL 提供向量化作业状态和向量结果查询 API，让当前用户查看自己文档的向量化状态与向量数据。

#### Scenario: 查询当前用户向量化作业状态
- **WHEN** 当前用户请求 `GET /api/document-embedding-jobs/{job_id}`
- **AND** 向量化作业属于当前用户
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含 `id`、`chunk_job_id`、`parsed_document_id`、`status`、`embedder_name`、`embedding_dim`、`chunk_count`、`error_code`、`error_message`、`started_at`、`finished_at`

#### Scenario: 查询解析结果的最新向量化作业
- **WHEN** 当前用户请求 `GET /api/parsed-documents/{parsed_document_id}/embedding-job`
- **AND** 解析结果属于当前用户
- **AND** 该解析结果存在向量化作业
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含最新（非 `superseded`）向量化作业的状态
- **AND** 如果从未向量化则返回 `404`

#### Scenario: 分页查询活跃向量化结果
- **WHEN** 当前用户请求 `GET /api/parsed-documents/{parsed_document_id}/embeddings?offset=0&limit=50`
- **AND** 解析结果属于当前用户
- **AND** 该解析结果存在活跃向量化作业
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 按 `sequence_index` 返回分页向量列表
- **AND** 每条结果 MUST 包含 `id`、`chunk_id`、`sequence_index`、`embedding`（全量 float 数组）、`created_at`
- **AND** 没有活跃作业时返回空页

#### Scenario: 查询单个 chunk 的活跃向量
- **WHEN** 当前用户请求 `GET /api/document-chunks/{chunk_id}/embedding`
- **AND** chunk 属于当前用户
- **AND** chunk 存在活跃向量化作业的向量
- **THEN** API MUST 返回 `200`
- **AND** 响应体 MUST 包含 `id`、`chunk_id`、`embedding`、`embedder_name`、`embedding_dim`、`created_at`

#### Scenario: 阻止读取其他用户的向量化结果
- **WHEN** 当前用户请求不属于自己的向量化作业或向量
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST NOT 暴露其他用户的向量数据、配置快照或错误详情

### Requirement: 向量化配置
系统 SHALL 通过配置管理向量化开关、Embedding 服务地址、API Key、模型名称、维度、batch 大小、超时和重试次数。

#### Scenario: 读取默认向量化配置
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取 `DOCUMENT_EMBEDDING_ENABLED` 向量化开关
- **AND** 默认 base_url MUST 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **AND** 默认模型 MUST 为 `text-embedding-v3`
- **AND** 默认维度 MUST 为 `1024`
- **AND** 默认 batch_size MUST 为 `10`
- **AND** 默认超时 MUST 为 `60.0` 秒
- **AND** 默认最大重试次数 MUST 为 `3`

#### Scenario: 配置快照随作业持久化
- **WHEN** 系统创建向量化作业
- **THEN** 系统 MUST 将本次使用的 base_url、model、dimensions、batch_size 保存到 `embed_config_json`

#### Scenario: API Key 通过环境变量注入
- **WHEN** 系统初始化 Embedding 适配器
- **THEN** 适配器 MUST 从配置中读取 `DOCUMENT_EMBEDDING_API_KEY`
- **AND** API Key MUST NOT 硬编码在代码中
- **AND** API Key MUST NOT 出现在向量化作业的 `embed_config_json` 快照中

### Requirement: 向量化作业关闭收尾
系统 SHALL 在 graceful shutdown 期间对无法继续完成的向量化作业写入明确失败状态，并在向量化执行路径中检查关闭状态。

#### Scenario: 关闭时标记 queued 向量化作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `queued` 的向量化作业
- **THEN** 系统 MUST 将该向量化作业状态更新为 `failed`
- **AND** `error_code` MUST 为 `process_shutdown`
- **AND** `error_message` MUST 表达进程关闭导致作业未完成

#### Scenario: 关闭时标记 running 向量化作业失败
- **WHEN** graceful shutdown 开始
- **AND** 存在状态为 `running` 的向量化作业
- **THEN** 系统 MUST 将该向量化作业状态更新为 `failed`
- **AND** `error_code` MUST 为 `process_shutdown`

#### Scenario: 向量化执行中检测关闭信号
- **WHEN** 向量化作业正在执行 batch API 调用
- **AND** 进程进入 graceful shutdown
- **THEN** 系统 MUST 在下一个 batch 调用前检测到关闭状态
- **AND** 系统 MUST 将向量化作业标记为 `failed`
- **AND** `error_code` MUST 为 `process_shutdown`
- **AND** 已写入的向量 MAY 保留（最终一致性由调用方通过作业状态判断）

### Requirement: 首版向量化范围边界
系统 SHALL 将首版向量化限定为生成可检索的语义向量，不在本能力中实现语义检索、RAG 问答、混合检索或 pgvector 高级索引。

#### Scenario: 向量化完成后不启用检索
- **WHEN** 向量化作业状态变为 `succeeded`
- **THEN** 系统 MUST NOT 在本变更中实现语义检索 API
- **AND** 系统 MUST NOT 在本变更中实现 RAG 问答能力
- **AND** 系统 MUST NOT 在本变更中创建 pgvector HNSW 或 IVFFlat 索引
- **AND** 系统 MUST NOT 在本变更中实现混合检索（向量 + 全文 + 元数据过滤）