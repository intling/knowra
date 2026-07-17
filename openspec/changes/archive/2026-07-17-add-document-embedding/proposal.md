## Why

knowra 已完成文件上传、文档解析和文档分块能力，能够将用户私有资料转化为可追溯的 token 感知 chunk。但当前系统缺少将 chunk 文本转化为稠密向量的能力，语义检索和 RAG 问答无法开展。本次变更在分块能力基础上，引入基于云端 embedding API 的文档向量化模块，将每个 chunk 的文本转化为固定维度向量并持久化，为后续向量存储和语义检索提供标准化的向量输入。

## What Changes

- 新增云端 embedding API 配置项（`DOCUMENT_EMBEDDING_*`），支持配置 API 地址、密钥、模型名称、维度、批大小、超时和重试策略
- 新增 `document_embedding_jobs` 表，追踪向量化作业的生命周期（queued → running → succeeded / failed / superseded）
- 新增 `document_embeddings` 表，将每个 chunk 对应的向量以 JSON 浮点数组持久化（首版不写入 pgvector 向量索引列）
- 实现 OpenAI 兼容的 `EmbeddingAdapter`，封装 `openai` SDK 调用、批量拆分、重试和超时逻辑，不对外暴露第三方 SDK 类型
- 实现 `DocumentEmbeddingService`，管理向量化作业的创建、执行、持久化、取代旧结果和失败处理
- 分块成功后自动触发首次向量化（与"解析即分块"模式一致），使用 `contextualized_text` 作为向量化输入
- 提供重新向量化 API（`POST /api/document-chunk-jobs/{id}/re-embed`），支持切换模型或维度
- 提供向量化作业和向量结果查询 API，遵循与分块/解析相同的权限模型
- 支持 graceful shutdown 期间标记未完成向量化作业并拒绝新请求
- 首版明确不包含 pgvector 向量索引写入和语义检索能力，这些将在后续独立变更中实现

## Capabilities

### New Capabilities

- `document-embedding`: 文档向量化能力，将分块后的 chunk 文本通过云端嵌入模型转化为稠密向量并持久化，管理向量化作业生命周期，支持首次自动向量化和重新向量化，为后续语义检索提供标准化的向量输入。

### Modified Capabilities

## Impact

- **后端**：新增 `DOCUMENT_EMBEDDING_*` 配置项（`core/config.py` + `.env` / `.env.example`）；新增 `DocumentEmbeddingJob` 和 `DocumentEmbedding` 数据模型及 Alembic migration（`models/document_embedding.py`）；新增 `EmbeddingAdapter` 适配器（`services/embedding_adapter.py`），依赖 `openai` Python SDK；新增 `DocumentEmbeddingService` 服务（`services/document_embedding.py`）；新增 API 路由（`api/routes/document_embedding.py`），挂载于 `/api` 前缀；在现有解析后台任务中接入自动向量化触发逻辑；在现有 graceful shutdown 流程中接入向量化作业收尾
- **前端**：分块完成后展示向量化状态（中/完成/失败），提供重新向量化入口和向量预览组件；前端必须明确向量化完成不等于可搜索或可问答
- **数据库**：新增 `document_embedding_jobs` 和 `document_embeddings` 两张表及其索引，需要创建 Alembic migration
- **外部依赖**：依赖云端 embedding API（tumuer.me `Qwen/Qwen3-Embedding-0.6B`），需要配置有效的 `DOCUMENT_EMBEDDING_API_KEY`
- **不影响现有 API 契约**：现有解析、分块 API 的路径、请求/响应结构不变；向量化失败不回滚解析或分块结果
