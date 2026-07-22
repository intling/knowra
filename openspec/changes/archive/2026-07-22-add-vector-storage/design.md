## Context

knowra 使用 PostgreSQL 18 + pgvector 容器（`pgvector/pgvector:pg18`），pgvector 扩展已通过迁移 `20260514_0001` 启用，Python 包 `pgvector>=0.4.0` 已在 `pyproject.toml` 中。当前 `document_embeddings` 表以 JSON 浮点数组（`embedding_json`）存储 2560 维向量，完全未利用 pgvector 的原生能力。

本变更是向量能力路线图的第一步（Vector Storage → Vector Index → Semantic Search → Hybrid Search），目标是建立 pgvector 原生向量列，为后续索引和检索提供存储基础。

上游依赖：`document-embedding`（已完成）—— chunk 文本已通过云端 API 向量化并持久化到 `embedding_json`。
下游消费者：向量索引变更（后续独立变更）—— 将在 `embedding_vector` 列上创建 HNSW/IVFFlat 索引。

## Goals / Non-Goals

**Goals:**

- 在 `document_embeddings` 表新增 `embedding_vector vector(2560)` 列
- 实现双写策略：新生成的向量同时写入 `embedding_json`（JSON）和 `embedding_vector`（pgvector 原生类型）
- 对既有 `embedding_json` 数据执行安全分批回填到 `embedding_vector`
- 更新 `DocumentEmbedding` 模型和 `_save_embeddings()` 服务方法
- 提供完整的迁移测试、双写验证测试和回填验证测试

**Non-Goals:**

- 不创建向量索引（HNSW / IVFFlat）
- 不实现语义搜索 API
- 不实现混合检索（BM25 + 向量）
- 不修改现有 API 响应格式
- 不删除 `embedding_json` 列
- 不修改 chunk 或 segment 模型
- 不涉及前端变更

## Decisions

### 决策 1：使用 pgvector 原生 `vector(2560)` 类型，而非继续仅用 JSON

**选择**: 新增 `embedding_vector vector(2560)` 列，与现有 `embedding_json` JSON 列并存。

**替代方案**:
- **仅用 JSON（当前状态）**: 无法创建 pgvector 索引，无法在数据库层做向量运算，无法扩展。
- **替换 JSON 列（删除 `embedding_json`）**: 失去人类可读性和故障恢复备份，风险过高。
- **引入独立向量数据库（Milvus/Qdrant/Chroma）**: 增加运维复杂度、数据一致性问题，个人项目规模不匹配。

**理由**: pgvector 零新增基础设施（扩展已启用、包已安装），与 PostgreSQL 事务内联（向量搜索 + 用户过滤 + JOIN 元数据在一条 SQL 中完成），运维简单（备份 PG 即备份向量），规模完全匹配个人知识库场景（万到十万级 chunk）。保留 JSON 列提供可读参考和回退能力。

### 决策 2：双写策略（JSON + vector 列并存）

**选择**: 在 `_save_embeddings()` 中同时写入 `embedding_json` 和 `embedding_vector`。

**理由**: 
- JSON 列保留作为人类可读参考（数据库管理工具可直接查看向量值）
- 如果 pgvector 操作出现问题，JSON 列可作为回退数据源
- 现有 API 读取 `embedding_json` 的逻辑完全不受影响（向后兼容）
- 存储开销可接受：每个 2560 维向量约 20KB（JSON 文本）+ 10KB（vector 二进制），万级约 300MB

### 决策 3：从 JSON 列回填，而非重新调用 embedding API

**选择**: 使用 `embedding_json::vector` 类型转换从既有 JSON 数据回填到 `embedding_vector`。

**替代方案**: 重新调用云端 embedding API 为所有 chunk 生成向量。这会产生不必要的 API 费用、网络延迟和 token 消耗。

**理由**: `embedding_json` 已包含完整的 2560 维浮点数组，pgvector 的 `::vector` 转换是纯 CPU 操作，无需 IO。回填是纯数据库内操作。

### 决策 4：分批回填 + 幂等设计

**选择**: 使用 `WHERE embedding_vector IS NULL LIMIT N` 分批更新，每批 500 行，批次间提交事务。支持幂等重跑。

**理由**: 
- 避免长时间表锁阻塞线上写入
- 中断后可从中断点附近继续（`WHERE embedding_vector IS NULL`）
- 纯 DDL 操作，不涉及 IO，每批执行时间在秒级

### 决策 5：`embedding_vector` 列初始 nullable，回填后添加 NOT NULL 约束

**选择**: 列在 `ADD COLUMN` 时初始允许 NULL（支持渐进式回填），回填验证通过后立即通过 `ALTER COLUMN SET NOT NULL` 添加 NOT NULL 约束。

**理由**: 渐进式回填策略要求列在回填完成前可为空。新写入（双写）始终填充两列，旧数据在回填中逐步补全。回填完成后添加 NOT NULL 约束可以在数据库层强制完整性，防止未来意外写入 NULL 值。此约束在同一个迁移中完成，无需等待后续变更。

### 决策 6：使用 `pgvector.sqlalchemy.Vector` 类型，与 JSON 列声明模式一致

**选择**: 在 SQLModel 模型中使用 `sa_column=Column(Vector(2560))` 声明 `embedding_vector` 字段，与现有 `embedding_json` 的 `sa_column=Column(JSON)` 模式一致。

**理由**: SQLModel 无法直接类型化 pgvector 的 `Vector` 类型（与 `JSON` 列类似），使用 `sa_column` 绕过 SQLModel 的类型系统。运行时 pgvector 库会自动处理 Python `list[float]` ↔ pgvector `vector` 的序列化。

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 回填期间阻塞线上写入 | 中 | 分批提交，每批 500 行；`WHERE embedding_vector IS NULL` 支持幂等续跑 |
| pgvector Python 版本与 DB 扩展版本不匹配 | 中 | 使用 `pgvector/pgvector:pg18` 最新镜像 + `pgvector>=0.4.0`；CI 中验证 `CREATE EXTENSION vector` + 建表 + 插入 + 查询 |
| 双写增加磁盘空间 | 低 | 每行约增加 10KB，1 万条 embedding 约 100MB，对知识库体量可接受 |
| 未来模型维度变更（如 2560→4096） | 中 | pgvector 要求索引列维度固定；在 `dimensions` 列中记录维度以支持未来迁移；此风险在重新向量化能力中已部分覆盖 |
| 回填后 JSON 列与 vector 列数据不一致 | 中 | 回填完成后抽样验证：`SELECT COUNT(*) FROM document_embeddings WHERE embedding_vector IS DISTINCT FROM embedding_json::vector` |
| JSON 中存在非数值或维度错误数据 | 低 | 回填前执行预检：`SELECT id FROM document_embeddings WHERE jsonb_array_length(embedding_json) != 2560`；异常行跳过并记录日志 |

## Migration Plan

### 部署步骤

1. 运行 Alembic upgrade：添加 `embedding_vector vector(2560)` 列
2. 迁移自动执行数据回填（分批 `embedding_json::vector` → `embedding_vector`）
3. 验证回填完整性（`SELECT COUNT(*) WHERE embedding_vector IS NULL` 应为 0）
4. 回填验证通过后添加 NOT NULL 约束（`ALTER COLUMN embedding_vector SET NOT NULL`）
5. 新写入自动双写，无需额外操作

### 回滚策略

1. 运行 Alembic downgrade：删除 `embedding_vector` 列
2. 双写代码已部署但列不存在时：`_save_embeddings()` 写入 `embedding_vector` 会因列不存在而失败——回滚时必须同时回滚代码
3. 推荐流程：先回滚代码（移除 `embedding_vector` 写入），再回滚迁移

### 数据完整性验证

```sql
-- 预检：确认所有 JSON 向量维度正确
SELECT COUNT(*) FROM document_embeddings 
WHERE jsonb_array_length(embedding_json::jsonb) != 2560;

-- 回填完成度
SELECT COUNT(*) FROM document_embeddings WHERE embedding_vector IS NULL;

-- 新旧列一致性抽样
SELECT COUNT(*) FROM document_embeddings 
WHERE embedding_vector IS DISTINCT FROM embedding_json::vector;
```

## Open Questions

- 后续 HNSW 索引的距离度量选择（cosine / L2 / inner_product）？需根据 `Qwen3-Embedding-4B` 模型的训练方式确定，将在向量索引变更中决策。
