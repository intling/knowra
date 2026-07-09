## Why

当前 knowra 已完成文档解析与分块，能将用户上传的资料转化为结构化的文本块（`document_chunks`），但这些文本块尚无法被语义检索消费——它们只是文本，缺乏可计算的语义表示。要实现"用户提问 → 检索相关片段 → 生成带引用回答"这一核心 RAG 工作流，必须先为每个 chunk 生成语义向量并持久化到 pgvector 向量数据库。本变更在分块结果之上，引入云端 Embedding 模型调用与向量存储能力，为后续语义检索和 RAG 问答奠定基础。

## What Changes

- 新增 `document_embedding_jobs` 表，记录向量化作业的生命周期（状态、模型名、维度、配置快照、错误信息）
- 新增 `document_chunk_embeddings` 表，以 pgvector `vector(1024)` 类型存储每个 chunk 的语义向量
- 新增 `OpenAIEmbeddingAdapter`，封装 OpenAI 兼容的 `/v1/embeddings` API 调用，支持通过配置切换千问、OpenAI、豆包等任意兼容服务
- 新增 `DocumentEmbeddingService`，编排向量化作业的创建、chunk 文本读取、批量调用适配器、结果持久化
- 分块作业成功后自动在同一后台任务中触发向量化，无需用户手动操作
- 重新分块（`/rechunk`）成功后自动触发重新向量化，旧向量化作业标记为 `superseded`
- 新增 `POST /api/parsed-documents/{id}/reembed` API，支持在分块结果不变的情况下更换模型参数重新向量化
- 新增向量化作业状态查询与向量结果分页查询 API
- 新增向量化相关配置项：开关、base_url、api_key、model、dimension、batch_size 等

## Capabilities

### New Capabilities
- `document-embedding`: 文档向量化能力——将分块后的文本块通过云端 Embedding 模型转化为语义向量，存储到 pgvector 向量数据库，为后续语义检索与 RAG 问答提供基础。包含向量化作业管理、OpenAI 兼容适配器、自动触发与独立重向量化。

### Modified Capabilities
- `document-chunking`: 分块作业成功后自动触发向量化流程；重新分块成功后自动触发重新向量化；分块被 supersede 时联动向量化作业 supersede。

## Impact

- **新增模型**: `DocumentEmbeddingJob`、`DocumentChunkEmbedding`（SQLModel 表，含 pgvector `vector(1024)` 列）
- **新增服务**: `OpenAIEmbeddingAdapter`、`DocumentEmbeddingService`
- **新增 API**: `GET /api/document-embedding-jobs/{job_id}`、`GET /api/parsed-documents/{id}/embedding-job`、`GET /api/parsed-documents/{id}/embeddings`、`GET /api/document-chunks/{chunk_id}/embedding`、`POST /api/parsed-documents/{id}/reembed`
- **新增配置**: `DOCUMENT_EMBEDDING_ENABLED`、`DOCUMENT_EMBEDDING_BASE_URL`、`DOCUMENT_EMBEDDING_API_KEY`、`DOCUMENT_EMBEDDING_MODEL`、`DOCUMENT_EMBEDDING_DIM`、`DOCUMENT_EMBEDDING_BATCH_SIZE`、`DOCUMENT_EMBEDDING_TIMEOUT`、`DOCUMENT_EMBEDDING_MAX_RETRIES`、`DOCUMENT_EMBEDDING_EXTRA_BODY`
- **新增 Migration**: Alembic 创建 `document_embedding_jobs` 和 `document_chunk_embeddings` 表
- **修改文件**: `config.py`（新增配置项）、`router.py`（注册路由）、`document_parse_dispatcher.py`（分块后自动向量化）、`document_chunking.py`（重分块后自动向量化）
- **外部依赖**: 阿里云 DashScope text-embedding-v3（OpenAI 兼容 /v1/embeddings），需要有效的 API Key
- **pxgvector 列**: 维度固定为 1024，与 text-embedding-v3 默认维度对齐