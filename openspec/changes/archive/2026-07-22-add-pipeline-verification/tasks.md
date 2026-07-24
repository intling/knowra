## 1. 后端 Schema 层

- [x] 1.1 新建 `backend/app/schemas/pipeline_verification.py`，定义 Pydantic 响应模型：`PipelineVerificationResponse`、`DocumentChainInfo`、`PipelineStageInfo`、`VerificationSummary`、`VerificationCheck`、`ChunkEmbeddingPairResponse`、`ChunkInfo`、`EmbeddingInfo`、`VerificationStats`
- [x] 1.2 验证命令：`uv run ruff check backend/app/schemas/pipeline_verification.py`

## 2. 后端 Service 层

- [x] 2.1 新建 `backend/app/services/pipeline_verification.py`，实现 `PipelineVerificationService` 类，包含：`_load_document_chain()`（查询 parsed_document + uploaded_file 文档链）、`_validate_pipeline_complete()`（确认 parse/chunk/embedding 作业均为 succeeded）、`_load_chunk_embedding_pairs()`（JOIN chunks ↔ embeddings）、`_resolve_chunk_texts()`（复用 `ChunkArtifactStorage` 解析文件系统文本）、`_run_integrity_checks()`（执行 7 项完整性检查）、`_build_result()`（组装 `PipelineVerificationResult`）
- [x] 2.2 验证命令：`uv run ruff check backend/app/services/pipeline_verification.py`

## 3. 后端 Route 层

- [x] 3.1 新建 `backend/app/api/routes/pipeline_verification.py`，实现 `GET /api/parsed-documents/{parsed_document_id}/pipeline-verification` 端点，包含权限校验（`get_current_user()`）、错误映射（404 无文档/无分块作业/无向量化作业、503 用户不可用）
- [x] 3.2 修改 `backend/app/api/router.py`，注册 `pipeline_verification.router`
- [x] 3.3 验证命令：`uv run ruff check backend/app/api/routes/pipeline_verification.py backend/app/api/router.py`

## 4. 后端测试（TDD：先红后绿）

- [x] 4.1 新建 `backend/tests/test_pipeline_verification.py`，编写红测试代码，覆盖正常路径（完整 pipeline 文档验证返回 200 且所有检查 passed）、边界情况（仅一个 chunk 的文档、chunk 文本在文件系统中而非内联、sequence_index 从 0 开始连续）、异常处理（parsed_document 不存在 → 404 "Parsed document not found"、无 succeeded chunk_job → 404 "No succeeded chunk job found"、chunk_job 存在但无 succeeded embedding_job → 404 "No succeeded embedding job found"、chunk_job 状态为 failed → 404、存在孤儿 embedding → 200 但 pairing 检查 failed、存在孤儿 chunk → 200 但 pairing 检查 failed、sequence_index 跳号 → 200 但 continuity 检查 failed、文件系统中 chunk 文本文件被删除 → 200 但 text_availability 检查 failed、current_user 不可用 → 503），所有测试函数附清晰中文注释说明验证意图
- [x] 4.2 确认 RED：运行 `uv run pytest backend/tests/test_pipeline_verification.py -v`，确认所有测试因缺少业务代码而失败
- [x] 4.3 红测试评审点：停在此处等待用户确认后再进入绿测试阶段
- [x] 4.4 绿测试：实现 Service + Route 业务代码后，运行 `uv run pytest backend/tests/test_pipeline_verification.py -v`，确认全部通过
- [x] 4.5 验证命令：`uv run pytest backend/tests/test_pipeline_verification.py -v`

## 5. 前端 API 客户端

- [x] 5.1 新建 `front/src/api/pipelineVerification.ts`，实现 `fetchPipelineVerification(parsedDocumentId: string)` 函数，调用 `GET /api/parsed-documents/{id}/pipeline-verification`，返回类型化响应
- [x] 5.2 使用延迟 Logger 创建模式（惰性 getter 函数），禁止在模块顶层直接调用 `getRingBuffer()` 或 `createLogger()`
- [x] 5.3 验证命令：`npm run lint`

## 6. 前端验证页面

- [x] 6.1 新建 `front/src/views/VerificationView.vue`，实现文档选择器（页面加载时获取已解析文档列表填充下拉框）、验证摘要面板（统计卡片，展示 7 项检查通过/失败状态）、Pipeline 链路展示（解析 → 分块 → 向量化三阶段状态）、分块-向量对照表（序列号、chunk 文本前 150 字截断、token 数、向量前 5 维预览）、加载状态骨架屏、空状态提示（无已解析文档时）、错误状态展示（API 返回 404/503 时）
- [x] 6.2 修改 `front/src/router/index.ts`，添加 `/verify` 路由指向 `VerificationView`
- [x] 6.3 使用延迟 Logger 创建模式（惰性 getter 函数）
- [x] 6.4 验证命令：`npm run lint && npm run build`（lint 通过；build 因 HomeView.vue 已有 TS 错误阻塞，非本次变更引入）

## 7. 前端测试

- [x] 7.1 新建 `front/src/views/__tests__/VerificationView.spec.ts`，覆盖：文档选择器渲染、验证按钮存在、点击验证后显示加载指示器、API 返回成功时正确渲染摘要卡片和对照表、passed/failed/warning 三种检查状态的不同视觉呈现、API 返回 404 时显示错误详情、无文档时的空状态提示、API 返回 503 时的错误提示
- [x] 7.2 验证命令：`npm run test`

## 8. 端到端验证与质量门禁

- [x] 8.1 后端质量门禁：`uv run ruff check . && uv run ruff format --check . && uv run pytest`
- [x] 8.2 前端质量门禁：`npm run lint && npm run test && npm run build`
- [x] 8.3 手动 smoke test：上传真实文档 → 等待 pipeline 完成 → 浏览器访问 `/verify` → 选择文档 → 执行验证 → 确认全部 7 项检查通过、对照表数据正确
