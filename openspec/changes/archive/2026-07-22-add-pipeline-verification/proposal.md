## Why

knowra 已完成写入侧全部模块的单独测试（上传 → 解析 → 分块 → 向量化 → pgvector 存储），但端到端的存取验证尚未进行。核心缺失：向量已写入 `document_embeddings` 表，但从未验证能否将向量取出并通过 JOIN 链路还原为原始分块内容。如果存在孤儿向量、缺失文本、维度不一致或序号断裂等问题，当前系统无法发现，这将为后续语义搜索和 RAG 阶段埋下严重隐患。

## What Changes

- 新增只读验证 API `GET /api/parsed-documents/{id}/pipeline-verification`，沿 JOIN 链路还原「向量 → 分块 → 文档」的完整数据
- 新增 `PipelineVerificationService` 服务层，负责文档链加载、chunk-embedding JOIN、文件系统文本解析、完整性检查执行和结果组装
- 新增 Pydantic Schema 定义验证响应的结构化模型
- 新增前端验证页面 `/verify`，包含文档选择器、Pipeline 链路展示、验证摘要面板和分块-向量对照表
- 实现 7 项数据完整性检查：分块-向量对应关系、向量维度一致性、序号连续性、分块文本可读性、上下文增强文本可读性、Token 数有效性和嵌入模型一致性
- 编写后端单元测试与集成测试（覆盖正常路径、边界情况和异常分支）
- 编写前端组件测试（覆盖渲染、加载、成功、空状态和错误状态）
- **不涉及**：数据库 migration（纯 SELECT 操作）、Docker 配置、环境变量变更、模型文件变更

## Capabilities

### New Capabilities
- `pipeline-verification`: 流水线存取验证能力 —— 从 pgvector 取出已存储向量，通过 JOIN 还原为原始分块文本，以结构化方式展示全链路数据完整性，提供 7 项自动化检查覆盖「向量 ↔ 分块」映射关系中所有可能的数据异常

### Modified Capabilities
<!-- None -->

## Impact

- **后端新增**：`backend/app/services/pipeline_verification.py`（核心服务）、`backend/app/api/routes/pipeline_verification.py`（路由处理）、`backend/app/schemas/pipeline_verification.py`（Pydantic 响应模型）
- **后端修改**：`backend/app/api/router.py`（注册新路由）
- **前端新增**：`front/src/api/pipelineVerification.ts`（API 客户端）、`front/src/views/VerificationView.vue`（验证页面组件）
- **前端修改**：`front/src/router/index.ts`（添加 `/verify` 路由）
- **测试新增**：`backend/tests/test_pipeline_verification.py`、`front/src/views/__tests__/VerificationView.spec.ts`
- **依赖的现有基础设施**：`ChunkArtifactStorage`（文件系统文本读取）、`get_current_user()`（权限校验）、现有 `document_embeddings`/`document_chunks`/`document_chunk_jobs`/`parsed_documents`/`uploaded_files` 数据模型
- **不涉及**：数据库 migration、环境变量、Docker 配置、嵌入模型文件
