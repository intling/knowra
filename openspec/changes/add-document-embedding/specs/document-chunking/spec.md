# document-chunking Delta Specification

## MODIFIED Requirements

### Requirement: 首版分块范围边界
系统 SHALL 将首版文档分块限定为生成可追溯 chunk，不在本能力中实现 embedding 模型、向量索引、语义检索或 RAG 问答。分块完成后将自动触发向量化流程（由 `document-embedding` 能力负责），但分块本身不包含向量化实现。

#### Scenario: 分块完成后不创建向量索引
- **WHEN** 分块作业状态变为 `succeeded`
- **THEN** 系统 MUST NOT 在本变更（分块能力）中创建 embedding 记录
- **AND** 系统 MUST NOT 在本变更（分块能力）中写入 pgvector chunk 索引
- **AND** 系统 MUST NOT 在本变更（分块能力）中启用语义检索或 RAG 问答能力

#### Scenario: 分块完成后可触发外部向量化
- **WHEN** 分块作业状态变为 `succeeded`
- **AND** 向量化功能配置为启用
- **THEN** 系统 MAY 在分块流程外部触发向量化
- **AND** 向量化行为 MUST 由 `document-embedding` 能力定义和实现
- **AND** 分块作业的 `succeeded` 状态 MUST NOT 依赖向量化是否成功

## ADDED Requirements

### Requirement: 分块成功后自动触发向量化
系统 SHALL 在分块作业成功后，在同一后台任务中自动触发向量化流程，将 chunk 文本传递给向量化服务。

#### Scenario: 自动分块成功后触发向量化
- **WHEN** `run_parse_job` 中分块作业执行成功（`status=succeeded`）
- **AND** 向量化功能配置为启用（`DOCUMENT_EMBEDDING_ENABLED=true`）
- **THEN** 系统 MUST 在同一后台任务中创建并执行向量化作业
- **AND** 向量化输入 MUST 使用当前分块作业生成的 `document_chunks` 记录
- **AND** 向量化失败 MUST NOT 影响分块作业的 `succeeded` 状态

#### Scenario: 向量化被禁用时跳过
- **WHEN** `DOCUMENT_EMBEDDING_ENABLED` 为 `false`
- **THEN** 系统 MUST NOT 触发向量化
- **AND** 分块流程 MUST 正常完成不受影响

#### Scenario: 分块失败时不触发向量化
- **WHEN** 分块作业执行失败（`status=failed`）
- **THEN** 系统 MUST NOT 创建向量化作业
- **AND** 系统 MUST NOT 调用 Embedding API

### Requirement: 重新分块成功后自动触发重新向量化
系统 SHALL 在重新分块（`/rechunk`）成功后，在同一后台任务中自动触发向量化，将旧向量化作业标记为 `superseded`。

#### Scenario: 重新分块成功后自动创建新向量化作业
- **WHEN** `run_rechunk_job` 中分块作业执行成功
- **AND** 向量化功能配置为启用
- **THEN** 系统 MUST 在同一后台任务中创建并执行向量化作业
- **AND** 新向量化作业 MUST 关联当前重新分块作业
- **AND** 新向量化作业成功后，旧向量化作业 MUST 被标记为 `superseded`

#### Scenario: 重新分块失败时不触发向量化
- **WHEN** 重新分块作业执行失败
- **THEN** 系统 MUST NOT 创建向量化作业
- **AND** 旧向量化作业 MUST 保持原有状态不变