## Why

knowra 已在 `document-embedding` 变更中完成文档向量化能力——chunk 文本通过 `Qwen/Qwen3-Embedding-4B` 云端 API 转化为 2560 维稠密向量，并以 JSON 浮点数组形式存储在 `document_embeddings.embedding_json` 列中。然而 JSON 列无法利用已就绪的 pgvector 扩展（PostgreSQL 18 + pgvector 容器已运行、扩展已启用、`pgvector>=0.4.0` Python 包已安装）进行原生向量操作。这意味着后续的向量索引（HNSW/IVFFlat）、语义检索和混合检索均无法在数据库层实现，必须在应用层加载全部数据再计算，无法扩展。

本变更在已完成向量化的基础上，引入 pgvector 原生 `vector(2560)` 类型列和双写策略，为后续向量索引和语义检索做好基础设施准备。**本阶段不实现向量索引和语义搜索**。

## What Changes

- 在 `document_embeddings` 表新增 `embedding_vector vector(2560)` 列（nullable），保留现有 `embedding_json` JSON 列作为人类可读参考和故障恢复备份
- 编写 Alembic 迁移：添加列 + 分批回填 `embedding_json::vector` → `embedding_vector`
- 更新 `DocumentEmbedding` 模型，新增 `embedding_vector` 字段（使用 `pgvector.sqlalchemy.Vector(2560)` 类型）
- 更新 `DocumentEmbeddingService._save_embeddings()` 实现双写：新生成的向量同时写入 `embedding_json` 和 `embedding_vector` 两列
- 编写迁移测试、双写正确性测试和回填验证测试
- **不创建**向量索引（HNSW/IVFFlat）——留待后续独立变更
- **不实现**语义搜索 API 或混合检索
- **不删除** `embedding_json` 列
- **不修改**现有 API 接口和前端行为

## Capabilities

### New Capabilities

- `vector-storage`: 在 `document_embeddings` 表中引入 pgvector 原生 `vector(2560)` 类型列，实现 JSON + vector 双写策略，对既有 `embedding_json` 数据执行安全回填，为后续向量索引和语义检索提供标准化的 pgvector 存储基础。

### Modified Capabilities

- `document-embedding`: 移除"向量化完成后不创建 pgvector 向量类型列"的约束（原 spec 中将 pgvector 列、索引、检索三者聚合在一起禁止），允许本变更创建 `embedding_vector` 列；`_save_embeddings()` 的行为从仅写入 `embedding_json` 变更为同时写入 `embedding_json` 和 `embedding_vector`；向量索引和语义检索在本阶段仍然不实现，留待后续独立变更。

## Impact

- **数据模型**: `DocumentEmbedding` 模型新增 `embedding_vector` 字段；`document_embeddings` 表新增 `vector(2560)` 列
- **Alembic 迁移**: 新增迁移文件，包含 DDL 和数据回填逻辑
- **服务层**: `DocumentEmbeddingService._save_embeddings()` 增加 `embedding_vector` 写入
- **依赖**: 启用已有的 `pgvector` Python 包（`pgvector.sqlalchemy.Vector` 类型）——无需新增依赖
- **配置**: 无需新增配置项
- **API**: 无变更——现有 API 响应继续返回 `embedding_json`，`embedding_vector` 作为内部存储列不对外暴露
- **前端**: 无变更
- **存储**: 新增向量二进制列带来约 10KB/行的额外存储（2560 维 × 4 字节），万级 embedding 约增加 100MB
