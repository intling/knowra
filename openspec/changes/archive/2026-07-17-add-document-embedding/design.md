## Context

knowra 已通过 `document-parsing` 和 `document-chunking` 能力完成了从上传文件到结构化 chunk 的完整文档处理管线。当前分块能力明确声明了范围边界：不实现 embedding、向量索引、语义检索或 RAG。本设计在此基础上引入独立的向量化模块，使用云端 embedding API 将每个 chunk 的文本转化为稠密向量，是 knowra 核心工作流中从"文档理解"过渡到"语义检索"的关键桥梁。

现有系统中分块作业（`document_chunk_jobs`）按 `parsed_document_id` 关联解析结果并持有 `succeeded` → `superseded` 的活跃结果取代语义；解析后台任务（`run_parse_job`）已内联分块触发逻辑。本设计的向量化作业将沿用同一模式：在分块成功后自动触发，且失败不回滚上游结果。

## Goals / Non-Goals

**Goals:**

- 定义向量化作业（`DocumentEmbeddingJob`）和向量结果（`DocumentEmbedding`）数据模型，遵循与 `DocumentChunkJob` / `DocumentChunk` 对齐的表结构和状态机
- 封装 OpenAI 兼容的云端 embedding API 适配器（`EmbeddingAdapter`），使用 `openai` SDK，不向调用方暴露第三方类型
- 实现 `DocumentEmbeddingService`，管理向量化作业的创建、批量执行、持久化、失败处理和活跃结果取代（supersede）
- 在分块成功后自动触发首次向量化，与"解析即分块"的自动触发模式保持一致
- 提供重新向量化 API（`POST /api/document-chunk-jobs/{id}/re-embed`），支持切换嵌入模型或维度，通过 BackgroundTasks 异步执行
- 提供向量化作业状态查询和向量结果查询 API，遵循现有权限模型
- 支持 graceful shutdown 收尾和协作式关闭检查，对齐现有解析/分块模块的关闭语义
- 采用 `DOCUMENT_EMBEDDING_*` 独立配置组，不复用现有 `DOCUMENT_CHUNK_*` 或 `DOCUMENT_MODEL_*` 配置

**Non-Goals:**

- **不写入 pgvector 向量索引列**（不创建 `vector(1024)` 类型列和 IVFFlat/HNSW 索引）
- **不实现语义检索**（不提供相似度查询 API）
- 不实现本地 embedding 模型推理
- 不实现多个 embedding 版本的并行维护（每次重新向量化 supersede 旧结果）
- 不包含 embedding API 调用的成本控制或速率限制

## Decisions

### 1. 采用 OpenAI 兼容 SDK 封装云端 API

**选择**：使用 `openai` Python SDK 发起 embedding 请求，通过 `EmbeddingAdapter` 封装。

**理由**：tumuer.me 提供 OpenAI 兼容的 `POST /v1/embeddings` 接口，可直接复用 `openai.Embeddings.create()` 方法。项目已依赖 `openai` 包，无需引入新的 HTTP 客户端。适配器封装后不向服务层暴露 `openai` 类型，方便未来切换为其他兼容服务（如 LiteLLM、vLLM 或本地 Ollama）。

**备选方案**：直接使用 `httpx` 构造 HTTP 请求。该方案虽然不依赖 `openai` SDK，但需要自行处理认证头、错误码映射、流式响应等细节，且当切换到其他 OpenAI 兼容服务时仍需重复这些工作。复用 SDK 的投入产出比更高。

### 2. 向量化文本选择 contextualized_text 优先

**选择**：向量化时使用 chunk 的 `contextualized_text`（如果非空），否则 fallback 到 `text`。

**理由**：`contextualized_text` 由 Docling HybridChunker 生成，携带了文档结构上下文（标题路径、章节标题等），比原始 `text` 更适合语义检索。这与 chunk 模型的设计意图一致。

### 3. 向量化作业独立于分块作业存在

**选择**：向量化作业通过 `chunk_job_id` 关联分块作业，但作为独立表存储。状态机与分块作业对齐（queued → running → succeeded / failed / superseded）。

**理由**：允许一个分块结果被多次向量化（切换模型或维度），而无需重新分块。同时保持数据模型清晰：分块作业关心 chunk 生成，向量化作业关心 embedding 生成。supersede 语义与分块作业一致：新成功的向量化作业将旧的 `succeeded` 作业标记为 `superseded`。

**备选方案**：将 embedding 列直接加在 `document_chunks` 表上。该方案简化了查询但丢失了作业追踪（无法知道 embedding 何时生成、使用哪个模型），且不支持多版本 embedding。

### 4. 首版不使用 pgvector 向量索引

**选择**：向量以 JSON 浮点数组（`embedding_json`）存储在 `document_embeddings` 表中，不创建 `vector(N)` 类型的 pgvector 列。

**理由**：向量存储（pgvector 索引写入）和语义检索是一个独立且复杂的变更——涉及 IVFFlat/HNSW 索引策略、距离度量、索引构建时机等。首版聚焦"生成向量"这一独立步骤，验证云端 API 的可用性和性能。向量以 JSON 形式持久化后，后续变更可直接读取已有 embedding 数据写入 pgvector 列，无需重新调用 API。

### 5. 自动触发链：分块成功后内联向量化

**选择**：在现有 `run_parse_job` 的后台执行流程中，分块完成后立即同步调用向量化服务。

**理由**：与"解析即分块"的设计一致，避免用户等待额外的异步调度。向量化失败不回滚解析和分块状态——这是 knowra 处理管线的基本原则：每个阶段独立成败。

**备选方案**：通过独立的后台任务或消息队列触发向量化。该方案增加了系统复杂度，且引入额外的延迟 —— 用户需要等待分块作业完成后再等待向量化作业被调度。

### 6. 重新向量化不复用旧 embedding 数据

**选择**：重新向量化时直接使用已有的 `document_chunks` 文本，重新调用云端 API。

**理由**：重新向量化的典型场景是切换模型或维度，旧向量与新需求不兼容。重新调用 API 保证数据一致性。已有 chunk 文本可直接读取，无需重新解析或分块。

## Risks / Trade-offs

- **[Risk] 云端 API 不可用或限流**：tumuer.me 为第三方服务。→ **缓解**：配置超时和重试策略（默认重试 3 次，指数退避）；向量化失败不阻塞分块成功状态；提供错误码 `api_error` 便于诊断。
- **[Risk] API 调用成本**：大批量文档向量化产生 API 调用费用。→ **缓解**：首版不做成本控制，后续可在配置中增加每日限额或成本追踪；单次失败只影响该作业，不影响其他文档。
- **[Trade-off] JSON 向量存储体积**：每个 1024 维向量以 JSON 数组存储约 8-12KB。→ **缓解**：这是过渡方案；后续向量存储变更中向量将迁移到 pgvector `vector(1024)` 类型列，`embedding_json` 届时可废弃。
- **[Risk] 自动向量化增加解析任务延迟**：在分块后同步调用云端 API 会增加整个后台任务耗时。→ **缓解**：云端 API 通常在数百毫秒到数秒内返回；失败作业不阻塞后续解析；向量化功能可通过配置开关禁用。
- **[Trade-off] 重新向量化需直接读取已有 chunks**：不会重新解析原始文件。→ **缓解**：这避免了不必要的重复解析和额外的外部依赖调用。chunk 文本已经持久化在数据库中或文件存储中，读取可靠。
