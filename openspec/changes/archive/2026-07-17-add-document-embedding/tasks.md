## 1. 配置与数据模型

- [x] 1.1 在 `backend/app/core/config.py` 中新增 `DOCUMENT_EMBEDDING_*` 配置项（`enabled`、`api_base_url`、`api_key`、`model`、`dimensions`、`encoding_format`、`batch_size`、`max_retries`、`request_timeout`），使用 Pydantic Settings 管理，提供默认值
- [x] 1.2 在 `backend/.env.example` 中新增 `DOCUMENT_EMBEDDING_*` 配置片段，使用占位符标注敏感配置
- [x] 1.3 创建 `backend/app/models/document_embedding.py`：定义 `DocumentEmbeddingJobStatus` 枚举（queued / running / succeeded / failed / superseded），定义 `DocumentEmbeddingJob` 和 `DocumentEmbedding` SQLModel 表模型，包含所有 spec 要求的字段和索引
- [x] 1.4 创建 Alembic migration 脚本，生成 `document_embedding_jobs` 和 `document_embeddings` 表
- [x] 1.5 创建 `backend/app/schemas/document_embedding.py`：定义 Pydantic 请求/响应 schema（`EmbeddingJobResponse`、`EmbeddingResponse`、`ReEmbedRequest`、分页响应），复用项目内分页模式
- [x] 1.6 在 `backend/app/models/__init__.py` 中导出新模型

## 2. 配置与数据模型测试（TDD RED）

- [x] 2.1 编写配置测试：验证 `DOCUMENT_EMBEDDING_*` 各项默认值，验证环境变量覆盖，验证 `api_key` 可从 `.env` 读取
- [x] 2.2 编写模型测试：验证 `DocumentEmbeddingJob` 创建时默认状态为 `queued`，验证状态枚举值约束，验证必需字段非空，验证 `config_json` 快照内容
- [x] 2.3 编写模型测试：验证 `DocumentEmbedding` 创建时字段完整性，验证 `embedding_json` JSON 数组存取，验证外键关联
- [x] 2.4 编写 schema 测试：验证响应 schema 序列化正确，验证 `ReEmbedRequest` 可选字段，验证分页响应结构
- [x] 2.5 运行 RED 测试确认全部失败（缺少实现代码），提交红测试供评审

## 3. Embedding 适配器

- [x] 3.1 创建 `backend/app/services/embedding_config.py`：定义 `EmbeddingConfig` dataclass，包含所有 API 连接参数；提供 `from_settings()` 工厂方法从应用配置构建
- [x] 3.2 创建 `backend/app/services/embedding_adapter.py`：实现 `EmbeddingAdapter` 类，使用 `openai` SDK 封装 `POST /v1/embeddings` 调用；定义 `EmbeddingResult` dataclass（index、embedding）；实现 `embed()` 批量方法（自动拆分超大批次）和 `embed_single()` 单文本方法
- [x] 3.3 实现适配器重试逻辑：网络超时和 5xx 错误使用指数退避自动重试，可配置 `max_retries` 和 `request_timeout`；重试耗尽时抛出项目内 `EmbeddingAPIError` 异常
- [x] 3.4 实现适配器响应校验：返回 `data` 数组长度与输入不匹配时抛出 `EmbeddingInvalidResponseError`；维度与配置不一致时包装错误信息

## 4. 适配器测试（TDD RED → GREEN）

- [x] 4.1 编写适配器测试（使用 mock）：验证单文本向量化返回正确 `EmbeddingResult`；验证批量文本向量化返回按输入顺序排列的结果
- [x] 4.2 编写适配器测试：验证超过 `batch_size` 时自动拆分为多个 API 调用，结果按原始顺序合并
- [x] 4.3 编写适配器测试：验证网络超时时自动重试，验证超过 `max_retries` 后抛出 `EmbeddingAPIError`
- [x] 4.4 编写适配器测试：验证 API 返回 5xx 时自动重试，验证 4xx（认证失败）时立即失败不重试
- [x] 4.5 编写适配器测试：验证返回数据长度不匹配时抛出 `EmbeddingInvalidResponseError`
- [x] 4.6 编写适配器测试：验证 `EmbeddingConfig.from_settings()` 正确映射配置项
- [x] 4.7 运行 RED 测试确认全部失败，编写 GREEN 实现使所有测试通过，重构保持测试通过

## 5. Embedding 服务

- [x] 5.1 创建 `backend/app/services/document_embedding.py`：实现 `DocumentEmbeddingService` 类，遵循与 `DocumentChunkingService` 相同的设计模式；构造函数接收 `session`、`adapter`、`config`、`shutdown_state` 参数
- [x] 5.2 实现 `run_initial_embedding()`：创建向量化作业（状态 `running`），调用 `_run_job()` 执行向量化，以 `supersede_previous=False` 模式运行（首次向量化无旧结果需取代）
- [x] 5.3 实现 `execute_queued_job()`：接收已创建的 QUEUED 作业和 chunks 列表，委托 `_run_job()` 执行，以 `supersede_previous=True` 模式运行；不调用 `_create_job()`
- [x] 5.4 实现 `_create_job()`：从 chunk_job 和 parsed_document 创建 `queued` 状态的 `DocumentEmbeddingJob`，保存 `config_json` 快照
- [x] 5.5 实现 `_run_job()`：更新作业状态为 `running`，收集 chunks 的 `contextualized_text`（优先）或 `text`（fallback）作为向量化输入，调用 `EmbeddingAdapter.batch_embed()`，持久化向量结果，更新作业为 `succeeded`
- [x] 5.6 实现批量持久化：`_save_embeddings()` 为每个 chunk 创建 `DocumentEmbedding` 记录，包含 `embedding_json`、`model`、`dimensions`、`token_count`、`sequence_index` 等字段
- [x] 5.7 实现活跃结果取代：`_supersede_previous_jobs()` 将同一 `chunk_job_id` 下的旧 `succeeded` 作业标记为 `superseded`
- [x] 5.8 实现错误处理：API 调用失败时捕获异常，将作业标记为 `failed`，记录 `error_code`（`api_error`、`invalid_response`）和 `error_message`，不抛出未捕获异常
- [x] 5.9 实现 shutdown 协作检查：向量化关键边界（API 调用前、写入成功前）检查 shutdown 状态，发现关闭时标记 `process_shutdown` 快速失败
- [x] 5.10 在所有关键路径添加结构化日志（作业创建、开始执行、完成、失败、shutdown 拦截），遵循项目日志规范

## 6. 服务测试（TDD RED → GREEN）

- [x] 6.1 编写服务测试：验证 `run_initial_embedding()` 创建作业并成功执行，mock 适配器返回固定向量
- [x] 6.2 编写服务测试：验证 `text` 选择策略 —— 当 `contextualized_text` 非空时优先使用，否则使用 `text`
- [x] 6.3 编写服务测试：验证 `_run_job()` 状态转换（queued/running → succeeded），验证 `embedding_count` 与 chunks 数量一致
- [x] 6.4 编写服务测试：验证 `_supersede_previous_jobs()` 正确将旧 `succeeded` 作业标记为 `superseded`，保留其他状态不变
- [x] 6.5 编写服务测试：验证 `execute_queued_job()` 不创建新作业，直接使用传入的 job 参数
- [x] 6.6 编写服务测试：验证适配器抛出异常时作业标记为 `failed`，`error_code` 正确，chunks 结果不变（不回滚）
- [x] 6.7 编写服务测试：验证 shutdown 期间 `queued` / `running` 作业被标记为 `process_shutdown`
- [x] 6.8 编写服务测试：验证 `execute_queued_job()` 在 shutdown 时快速失败，不调用适配器
- [x] 6.9 运行 RED 测试确认全部失败，编写 GREEN 实现使所有测试通过，重构保持测试通过

## 7. API 路由

- [x] 7.1 创建 `backend/app/api/routes/document_embedding.py`：实现 `GET /api/document-embedding-jobs/{job_id}` 查询向量化作业状态，校验当前用户权限
- [x] 7.2 实现 `GET /api/document-chunk-jobs/{chunk_job_id}/embeddings`：分页查询分块作业的最新活跃向量结果，按 `sequence_index` 排序
- [x] 7.3 实现 `GET /api/document-chunks/{chunk_id}/embedding`：查询单个 chunk 的向量详情
- [x] 7.4 实现 `POST /api/document-chunk-jobs/{chunk_job_id}/re-embed`：创建重新向量化作业（`202`），校验分块作业存在且属于当前用户，校验无运行中作业（`409`），校验 shutdown 状态（`503`），通过 `BackgroundTasks` 调度 `run_reembed_job`
- [x] 7.5 实现 `run_reembed_job` 后台执行函数：加载 QUEUED 作业、读取已有 chunks、调用 `DocumentEmbeddingService.execute_queued_job()`、处理失败，支持依赖注入便于测试
- [x] 7.6 在 `backend/app/api/router.py` 中注册新路由，挂载于 `/api` 前缀
- [x] 7.7 在所有 API 端点和后台执行函数中添加结构化日志（请求、权限拒绝、作业创建、执行完成/失败）

## 8. API 测试（TDD RED → GREEN）

- [x] 8.1 编写 API 测试：验证 `GET /api/document-embedding-jobs/{id}` 返回 `200` 和正确作业数据结构
- [x] 8.2 编写 API 测试：验证查询其他用户的向量化作业返回非 2xx 状态码
- [x] 8.3 编写 API 测试：验证 `GET /api/document-chunk-jobs/{id}/embeddings` 分页返回向量结果，按 `sequence_index` 排序
- [x] 8.4 编写 API 测试：验证 `GET /api/document-chunks/{id}/embedding` 返回单条向量详情
- [x] 8.5 编写 API 测试：验证 `POST /api/document-chunk-jobs/{id}/re-embed` 返回 `202` 和新建作业信息
- [x] 8.6 编写 API 测试：验证存在运行中作业时重新向量化返回 `409`
- [x] 8.7 编写 API 测试：验证 shutdown 期间重新向量化返回 `503`
- [x] 8.8 编写 API 测试：验证 `run_reembed_job` 后台执行器成功执行和失败处理
- [x] 8.9 编写 API 测试：验证 `run_reembed_job` shutdown 快速失败，作业标记为 `process_shutdown`
- [x] 8.10 编写 API 测试：验证 `run_reembed_job` 新结果成功后旧作业被标记为 `superseded`
- [x] 8.11 编写 API 测试：验证重新向量化不重新解析或分块（不调用 parser/chunker）
- [x] 8.12 运行 RED 测试确认全部失败，编写 GREEN 实现使所有测试通过，重构保持测试通过

## 9. 流程集成

- [x] 9.1 在 `backend/app/services/document_parsing.py` 的 `run_parse_job` 中，分块成功后接入自动向量化：检查 `DOCUMENT_EMBEDDING_ENABLED` 配置，启用时调用 `DocumentEmbeddingService.run_initial_embedding()`；禁用时跳过
- [x] 9.2 实现自动向量化失败不回滚逻辑：向量化失败时解析和分块作业保持 `succeeded`，仅向量化作业记录为 `failed`
- [x] 9.3 在 graceful shutdown 收尾流程中接入向量化作业：将 `queued` 和 `running` 的 `DocumentEmbeddingJob` 标记为 `failed`（`error_code=process_shutdown`），不修改已完成作业
- [x] 9.4 在所有集成节点添加结构化日志（自动触发、跳过、shutdown 收尾），遵循项目日志规范

## 10. 集成测试（TDD RED → GREEN）

- [x] 10.1 编写集成测试：验证解析 → 分块 → 向量化的完整自动链路，mock 适配器返回固定向量
- [x] 10.2 编写集成测试：验证向量化功能禁用时链路跳过，解析和分块仍成功
- [x] 10.3 编写集成测试：验证自动向量化失败时解析和分块保持 `succeeded`，向量化作业为 `failed`
- [x] 10.4 编写集成测试：验证 graceful shutdown 收尾正确标记向量化作业
- [x] 10.5 编写集成测试：验证重新向量化端到端流程（创建作业 → 后台执行 → 结果持久化 → 旧作业 superseded）
- [x] 10.6 运行 RED 测试确认全部失败，编写 GREEN 实现使所有测试通过，重构保持测试通过

## 11. 前端体验

- [x] 11.1 创建前端 embedding API 客户端模块（`front/src/api/embedding.ts`），封装向量化作业查询、向量结果查询和重新向量化请求，遵循项目延迟 Logger 创建模式
- [x] 11.2 在文档详情/分块结果页面展示向量化状态（中/完成/失败），使用分块作业 ID 查询关联的向量化作业
- [x] 11.3 实现向量预览组件：展示向量维度、模型名称和前几个维度值，不展示完整 1024 维数组
- [x] 11.4 实现重新向量化入口按钮和交互：点击触发 `POST /api/document-chunk-jobs/{id}/re-embed`，处理 `409`、`503` 等错误状态
- [x] 11.5 向量化中状态禁止重复触发，展示 loading 反馈和当前状态文案
- [x] 11.6 向量化完成状态展示维度/模型信息，提供预览入口；前端明确表示向量化完成不等于可搜索或可问答
- [x] 11.7 向量化失败状态展示用户可理解的错误反馈，保留重新向量化入口

## 12. 前端测试

- [x] 12.1 编写前端 API 客户端测试：验证请求路径、参数和错误处理
- [x] 12.2 编写向量化状态展示组件测试：覆盖向量化中 / 完成 / 失败 / 禁用四种状态
- [x] 12.3 编写重新向量化交互测试：验证按钮禁用逻辑、成功/失败反馈
- [x] 12.4 运行前端测试并确认通过：`npm run test`

## 13. 文档与质量门禁

- [x] 13.1 更新 `backend/.env.example` 添加 `DOCUMENT_EMBEDDING_*` 配置片段
- [x] 13.2 更新后端相关文档（README 或配置说明）描述新增环境变量和向量化功能
- [x] 13.3 运行后端代码质量检查：`uv run ruff check .` 和 `uv run ruff format --check .`
- [x] 13.4 运行全部后端测试：`uv run pytest`，确认全部通过（包括新增和既有测试）
- [x] 13.5 运行前端代码质量检查：`npm run lint`
- [x] 13.6 运行前端构建：`npm run build`，确认无构建错误
- [x] 13.7 执行全链路 smoke test：上传文档 → 解析 → 分块 → 向量化 → 查询向量结果 → 重新向量化 → 查询新结果，验证端到端流程
