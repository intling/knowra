# document-embedding Delta Specification

## MODIFIED Requirements

### Requirement: 向量结果模型

系统 SHALL 持久化每个 chunk 对应的向量结果，包括向量浮点数组、模型信息、维度和 token 消耗，以供后续向量存储、检索和来源追溯消费。

#### Scenario: 创建向量结果表结构

- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `document_embeddings` 表
- **AND** `document_embeddings` 表 MUST 包含 `id`、`embedding_job_id`、`chunk_id`、`parsed_document_id`、`owner_user_id`、`sequence_index`、`model`、`dimensions`、`embedding_json`、`embedding_vector`、`token_count`、`created_at` 字段
- **AND** 数据库 MUST 为 `embedding_job_id`、`chunk_id`、`owner_user_id` 和 `(parsed_document_id, sequence_index)` 提供可查询索引

#### Scenario: 向量结果按 chunk 顺序保存

- **WHEN** 向量化适配器生成一个或多个向量
- **THEN** 系统 MUST 将每个向量与对应 chunk 的 `sequence_index` 关联
- **AND** 每个向量结果 MUST 关联当前向量化作业、对应 chunk 和解析文档
- **AND** 每个向量结果 MUST 保存当前用户归属以支持权限过滤

#### Scenario: 向量以 JSON 浮点数组和 pgvector 原生格式双写存储

- **WHEN** 系统保存向量结果
- **THEN** `embedding_json` 字段 MUST 包含完整浮点数组（如 `[0.123, -0.456, ...]`）
- **AND** `embedding_vector` 字段 MUST 包含等价的 pgvector `vector(2560)` 原生向量
- **AND** `dimensions` 字段 MUST 记录数组长度
- **AND** `model` 字段 MUST 记录生成该向量的嵌入模型名称
- **AND** `token_count` 字段 MUST 记录向量化消耗的 token 数
- **AND** 系统 MUST NOT 在本能力中创建 IVFFlat 或 HNSW 索引

#### Scenario: 不修改既有 chunk 或 segment 记录

- **WHEN** 系统保存向量结果
- **THEN** 系统 MUST NOT 修改、删除、合并或覆盖既有 `document_chunks` 记录
- **AND** 系统 MUST NOT 修改、删除、合并或覆盖既有 `document_segments` 记录

### Requirement: 首版向量化范围边界

系统 SHALL 将首版文档向量化限定为生成并持久化 chunk 向量，不在本能力中实现 pgvector 向量索引、语义检索或 RAG。

#### Scenario: 向量化完成后不创建向量索引

- **WHEN** 向量化作业状态变为 `succeeded`
- **THEN** 系统 MUST NOT 在本变更中创建 IVFFlat 或 HNSW 索引
- **AND** 系统在本阶段 MUST NOT 启用语义检索或 RAG 问答能力
- **AND** 上述能力将在后续独立变更中实现
