## Context

knowra 已完成写入侧全部模块的单独测试（上传 → 解析 → 分块 → 向量化 → pgvector 存储），每个模块独立验证通过。但 `document_embeddings` 表中存有向量，`document_chunks` 表中存有分块文本，二者之间的关联是否完整、一致、可还原从未被端到端验证过。

当前项目已有完整的 Service → Route → Schema 分层架构、`ChunkArtifactStorage` 文件系统存储、`get_current_user()` 权限校验、以及 `get_latest_active_embedding_job()` 活跃作业查询等基础设施。本设计在复用这些组件的基础上，新增一条只读验证链路。

## Goals / Non-Goals

**Goals:**
- 提供一条只读 API，从 pgvector 取出向量并通过 JOIN 还原为原始分块文本，端到端验证「向量 → 分块 → 文档」的数据完整性
- 实现 7 项自动化完整性检查，覆盖向量-分块映射中所有可能的数据异常（孤儿记录、维度不一致、序号断裂、文本缺失、Token 无效、模型不一致）
- 提供前端验证页面，以结构化方式展示文档信息、Pipeline 链路、验证摘要和分块-向量对照表
- 同时作为后续语义搜索和 RAG 阶段的回归测试基础设施

**Non-Goals:**
- 不实现语义搜索（用户查询向量化、pgvector ANN 检索）
- 不实现 RAG 问答（LLM 生成、引用标注）
- 不修改任何数据库记录（纯 SELECT + 文件读取）
- 不添加数据库 migration、不修改环境变量、不引入新依赖
- 不实现批量文档验证

## Decisions

### 1. API 路径设计：挂载在 `parsed-documents` 资源下

**选择**：`GET /api/parsed-documents/{parsed_document_id}/pipeline-verification`

**替代方案考虑**：
- `/api/pipeline-verification/{parsed_document_id}` — 独立顶级路径，但 parsed_document 是验证的核心资源，嵌套路径更符合 REST 语义
- `/api/verify` 带 query param — 不符合项目现有 RESTful 风格

**理由**：遵循项目已有的资源嵌套模式（如 `/document-chunk-jobs/{chunk_job_id}/embeddings`），`pipeline-verification` 作为 `parsed-documents` 的子资源表达「对该文档执行验证」的语义。

### 2. 服务层设计：新建独立 Service 而非扩展已有 Service

**选择**：新建 `PipelineVerificationService`，接收 `Session` + `ChunkArtifactStorage`

**理由**：
- 验证是横切关注点，跨越 parsing、chunking、embedding 三个模块的边界
- 保持只读语义隔离，避免将查询逻辑混入写入侧的 `DocumentEmbeddingService`
- 作为后续阶段的回归测试基础设施，独立 Service 便于单独测试和复用

### 3. 完整性检查结果语义：始终返回 200，检查结果内嵌

**选择**：验证 API 始终返回 `HTTP 200`，即使部分检查失败。检查结果嵌入 `verification.checks[]` 数组中。

**替代方案考虑**：单条检查失败返回 4xx/5xx。

**理由**：允许前端同时展示所有检查项的状态（通过/失败/警告），而非在第一个失败处中断。完整性检查反映的是数据质量状态，不是 API 调用失败。当 pipeline 阶段缺失（无 chunk_job / 无 embedding_job）时返回 404 是合理的，因为那代表「请求本身无法执行」。

### 4. 向量预览策略：API 仅返回前 5 维

**选择**：`pairs[].embedding.vector_preview` 仅返回向量的前 5 个浮点数，而非全部 2560 维。

**理由**：大文档可能有数百个 chunk，每个 pair 返回完整 2560 维向量会导致响应体过大（单个 pair 约 30KB）。前端对照表仅需展示向量概览，完整向量可通过后续点击单条展开获取（可复用已有的 `GET /api/document-chunks/{chunk_id}/embedding` 端点）。

### 5. 文件系统文本解析：复用 ChunkArtifactStorage

**选择**：直接使用已有的 `ChunkArtifactStorage.path_for()` 将 `text_storage_key` 转换为文件系统路径并读取。

**理由**：`ChunkArtifactStorage` 已封装路径解析和校验逻辑，重新实现会导致路径拼接规则重复。当 `STORAGE_DIR` 配置变更时，所有使用者自动跟随更新。

### 6. 前端页面路由：独立 `/verify` 路由

**选择**：前端验证页面挂载在 `/verify`，不与现有文档管理页面耦合。

**替代方案考虑**：在文档详情页内嵌验证面板。

**理由**：验证页面是开发者/运维工具，不是终端用户的常规工作流。独立路由便于后续扩展（如批量验证、定时验证），且不影响现有文档管理页面的复杂度。

## Risks / Trade-offs

- **[性能] 大文档响应体积**：数百个 chunk 的文档会产生较大的 JSON 响应。缓解措施：向量预览仅返回前 5 维；对照表文本截断至前 200 字符。如果未来需要分页，可在 `pairs` 数组中添加 offset/limit 参数。
- **[依赖] 文件系统可用性**：文本解析依赖 `ChunkArtifactStorage` 能正确读取文件。如果 `storage/chunks/` 目录被手动清理，`chunk_text_availability` 检查会失败但不会导致 API 崩溃。`_resolve_chunk_texts()` 内部对单个文件读取失败进行 try/catch，标记该 pair 的文本为不可用并记录日志。
- **[安全] 权限校验**：所有端点必须通过 `get_current_user()` 校验用户身份，确保用户只能验证自己的文档。`parsed_document_id` 路径参数校验与所属用户绑定。
- **[可扩展性] 批量验证**：当前设计为单文档验证。如需批量验证，建议在前端循环调用而非后端实现，避免 N+1 查询放大。
- **[生命周期] 无后台任务**：本服务为纯请求-响应同步模型，无后台任务、无长连接、无文件句柄持有。不在请求处理中启动线程或子进程。服务实例在请求结束后随 Session 关闭自然消亡。不涉及 graceful shutdown 语义。

## Migration Plan

- 部署步骤：代码合并后，后端自动注册新路由（`router.py` 新增 include_router），前端自动注册新页面路由
- 回滚策略：回滚代码即可，无数据库 schema 变更，无数据迁移需求
- 数据库影响：无（纯 SELECT 操作，无 migration）
- 配置变更：无（不新增环境变量或配置项）

## Open Questions

- 无。方案已在 `docs/pipeline-verification-plan.html` 中经过充分设计，所有技术决策已明确。
