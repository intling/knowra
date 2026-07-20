# vector-storage Specification

## Purpose

在 `document-embedding` 已将 chunk 文本向量化并以 JSON 浮点数组持久化的基础上，引入 pgvector 原生 `vector(2560)` 类型列和双写策略，为后续向量索引（HNSW/IVFFlat）和语义检索提供标准化的 pgvector 存储基础。本能力仅建设存储基础设施，本阶段不创建向量索引、不实现语义搜索，向量索引和语义搜索将在后续独立变更中实现。

## ADDED Requirements

### Requirement: pgvector 原生向量列

系统 SHALL 在 `document_embeddings` 表中新增 `embedding_vector vector(2560)` 列，与现有 `embedding_json` JSON 列并存，接受 Python `list[float]` 通过 pgvector 库自动序列化为数据库原生向量类型。

#### Scenario: 列结构正确

- **WHEN** Alembic 迁移执行完成
- **THEN** 数据库 MUST 在 `document_embeddings` 表中存在 `embedding_vector` 列
- **AND** 列类型 MUST 为 `vector(2560)`
- **AND** 列在添加时 MUST 允许 NULL（以支持渐进式回填）
- **AND** 回填完成并验证通过后 MUST 添加 NOT NULL 约束

#### Scenario: 现有 JSON 列保持不变

- **WHEN** `embedding_vector` 列被添加
- **THEN** `embedding_json` 列 MUST 保持存在且数据完整
- **AND** 现有 API 读取 `embedding_json` 的行为 MUST 不受影响

#### Scenario: pgvector 类型接受 list[float] 写入

- **WHEN** 代码创建 `DocumentEmbedding` 实例并传入 `embedding_vector=[0.12, -0.45, ...]`（2560 个浮点数）
- **AND** 使用 SQLModel session 提交到数据库
- **THEN** 数据库 MUST 接受该写入
- **AND** 从数据库读回时 `embedding_vector` 字段 MUST 包含等价的浮点列表

### Requirement: 双写策略

系统 SHALL 在向量化服务持久化向量结果时，同时写入 `embedding_json`（JSON 格式）和 `embedding_vector`（pgvector 原生格式），确保两列包含相同向量数据。

#### Scenario: 新向量同时写入两列

- **WHEN** `DocumentEmbeddingService._save_embeddings()` 被调用
- **AND** 传入有效的 `EmbeddingResult` 列表
- **THEN** 系统 MUST 为每个 chunk 创建一条 `DocumentEmbedding` 记录
- **AND** 每条记录 MUST 同时包含非空的 `embedding_json` 和 `embedding_vector` 字段
- **AND** `embedding_json` 和 `embedding_vector` MUST 表示相同的向量值

#### Scenario: 双写不影响现有 API 响应

- **WHEN** 现有 API 查询向量结果（如 `GET /api/document-chunks/{chunk_id}/embedding`）
- **THEN** 响应体 MUST 继续包含 `embedding_json` 字段
- **AND** `embedding_vector` 字段 MUST NOT 出现在面向用户的 API 响应中

#### Scenario: 双写在同一事务中完成

- **WHEN** `_save_embeddings()` 写入向量结果
- **THEN** `embedding_json` 和 `embedding_vector` 的写入 MUST 在同一数据库事务中完成
- **AND** 两列的写入 MUST NOT 出现一个成功一个失败的情况

### Requirement: 既有数据回填

系统 SHALL 对 `document_embeddings` 表中已有 `embedding_json` 数据但 `embedding_vector` 为 NULL 的行执行回填，将 JSON 浮点数组转化为 pgvector 原生向量类型，无需重新调用 embedding API。

#### Scenario: 分批回填已有数据

- **WHEN** Alembic 迁移执行 upgrade
- **THEN** 迁移 MUST 对 `embedding_vector IS NULL` 的行执行分批 UPDATE
- **AND** 每批 MUST 不超过 500 行
- **AND** 每批 MUST 在独立事务中提交
- **AND** 回填 SQL MUST 使用 `embedding_json::vector` 类型转换

#### Scenario: 回填支持幂等重跑

- **WHEN** 回填被中断后重新执行
- **THEN** 已回填的行（`embedding_vector IS NOT NULL`）MUST 被跳过
- **AND** 未回填的行 MUST 继续被处理
- **AND** 幂等重跑 MUST NOT 导致数据重复或错误

#### Scenario: 回填前验证数据完整性

- **WHEN** 迁移执行回填前预检
- **THEN** 系统 SHOULD 检查是否存在 `jsonb_array_length(embedding_json) != 2560` 的行
- **AND** 对维度不匹配的行 SHOULD 跳过并记录警告日志

#### Scenario: 回填后验证完整度

- **WHEN** 回填完成
- **THEN** `SELECT COUNT(*) FROM document_embeddings WHERE embedding_vector IS NULL` MUST 返回 0
- **AND** 系统 SHOULD 抽样验证 `embedding_vector` 值与 `embedding_json` 值一致

### Requirement: 模型层支持 pgvector 类型

系统 SHALL 在 `DocumentEmbedding` SQLModel 模型中新增 `embedding_vector` 字段，使用 `pgvector.sqlalchemy.Vector(2560)` 类型声明，与现有 `sa_column=Column(...)` 模式一致。

#### Scenario: 模型字段声明正确

- **WHEN** `DocumentEmbedding` 模型被加载
- **THEN** `embedding_vector` 字段 MUST 使用 `pgvector.sqlalchemy.Vector(2560)` 类型
- **AND** 字段 MUST 通过 `sa_column=Column(Vector(2560), nullable=False)` 声明
- **AND** 字段 MUST 从 `pgvector.sqlalchemy` 导入 `Vector`

#### Scenario: 模型可用于创建新记录

- **WHEN** 测试代码创建 `DocumentEmbedding(embedding_vector=[0.1, 0.2, ...])` 并提交
- **THEN** 数据库 MUST 接受该记录
- **AND** 读回时 `embedding_vector` MUST 为对应的浮点列表

### Requirement: 本阶段不创建向量索引

系统 SHALL 在本变更中仅建设 pgvector 原生向量列存储基础设施。向量索引（HNSW / IVFFlat）和语义搜索属于后续独立变更的范畴，不在本阶段范围内。

#### Scenario: 本阶段不创建 HNSW 或 IVFFlat 索引

- **WHEN** 本变更的迁移和应用代码部署完成
- **THEN** 系统在本阶段 MUST NOT 在 `embedding_vector` 列上创建 HNSW 索引
- **AND** 系统在本阶段 MUST NOT 在 `embedding_vector` 列上创建 IVFFlat 索引
- **AND** 系统在本阶段 MUST NOT 提供语义搜索 API 端点
- **AND** 上述能力将在后续独立变更中实现

#### Scenario: embedding_vector 列可接受 pgvector 算子查询

- **WHEN** 开发者使用 pgvector 距离算子（如 `<=>`）在 SQL 中查询 `embedding_vector` 列
- **THEN** 查询 MUST 能正确执行（尽管未建立索引，精确搜索仍可用）
- **AND** 此行为仅供内部验证，不构成面向用户的 API

### Requirement: 迁移可逆

系统 SHALL 支持通过 Alembic downgrade 删除 `embedding_vector` 列，回退到仅 JSON 列的状态。

#### Scenario: downgrade 删除 vector 列

- **WHEN** Alembic downgrade 执行
- **THEN** `embedding_vector` 列 MUST 被删除
- **AND** `embedding_json` 列 MUST 保持完整
- **AND** 表中其他列 MUST 不受影响

#### Scenario: downgrade 后应用仍可运行

- **WHEN** `embedding_vector` 列被 downgrade 删除
- **AND** 应用代码仍尝试写入 `embedding_vector`
- **THEN** 写入会因列不存在而失败 —— 回滚时必须同时回滚应用代码
