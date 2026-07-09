## 1. 数据模型与 Migration

- [ ] 1.1 新增 `DocumentEmbeddingJob` 和 `DocumentChunkEmbedding` SQLModel 模型（`app/models/document_embedding.py`），`embedding` 列使用 pgvector `VECTOR(1024)` 类型
- [ ] 1.2 编写模型测试，验证表结构、字段默认值、状态枚举、外键约束和索引声明
- [ ] 1.3 新增 Alembic migration 创建 `document_embedding_jobs` 和 `document_chunk_embeddings` 表，`embedding` 列使用原始 SQL 创建
- [ ] 1.4 编写 migration 测试，验证 upgrade 创建表成功、downgrade 删除表成功、已有数据不受影响

## 2. 配置

- [ ] 2.1 在 `Settings` 类中新增 `DOCUMENT_EMBEDDING_ENABLED`、`DOCUMENT_EMBEDDING_BASE_URL`、`DOCUMENT_EMBEDDING_API_KEY`、`DOCUMENT_EMBEDDING_MODEL`、`DOCUMENT_EMBEDDING_DIM`、`DOCUMENT_EMBEDDING_BATCH_SIZE`、`DOCUMENT_EMBEDDING_TIMEOUT`、`DOCUMENT_EMBEDDING_MAX_RETRIES`、`DOCUMENT_EMBEDDING_EXTRA_BODY` 配置项
- [ ] 2.2 编写配置测试，验证默认值正确、环境变量解析正确、`extra_body` JSON 解析正确

## 3. Embedding 适配器

- [ ] 3.1 实现 `OpenAIEmbeddingAdapter`（`app/services/embedding_adapter.py`），包含 `embed()`、`dimension` 属性和 `model_name` 属性
- [ ] 3.2 适配器内部实现 batch 分片逻辑（按 `batch_size` 分片，循环发送 `POST /v1/embeddings`）
- [ ] 3.3 适配器支持 `extra_body` 透传（如 `text_type`）
- [ ] 3.4 适配器实现错误分类处理：401 不重试、404 不重试、ConnectionError 重试 3 次、超时重试 1 次
- [ ] 3.5 适配器实现维度探测与校验（首次调用时比对返回维度与配置维度）
- [ ] 3.6 编写适配器测试（Mock HTTP 响应）：验证正常 batch 调用、分片逻辑、维度探测、401/404/超时/连接失败的错误处理、`extra_body` 透传

## 4. 向量化服务

- [ ] 4.1 实现 `DocumentEmbeddingService`（`app/services/document_embedding.py`），包含 `run_initial_embedding()` 方法
- [ ] 4.2 服务内部实现 chunk 文本读取逻辑：优先 `contextualized_text`（DB 内联），fallback 到文件存储读取，再 fallback 到 `text`
- [ ] 4.3 服务内部实现作业生命周期管理：创建作业 → 标记 running → 批量调用适配器 → 逐条写入向量 → 标记 succeeded/failed
- [ ] 4.4 服务内部实现 supersede 逻辑：新作业成功后标记旧 `succeeded` 作业为 `superseded`
- [ ] 4.5 编写服务测试（Mock 适配器）：验证作业创建、文本读取（DB 内联/文件存储/fallback）、向量写入、supersede、作业失败原子性

## 5. 向量化 API 路由

- [ ] 5.1 新增 Pydantic schemas（`app/schemas/document_embedding.py`）：`DocumentEmbeddingJobRead`、`DocumentChunkEmbeddingRead`、`DocumentChunkEmbeddingPageRead`、`ReembedRequest`
- [ ] 5.2 实现 `GET /api/document-embedding-jobs/{job_id}` 查询作业状态
- [ ] 5.3 实现 `GET /api/parsed-documents/{parsed_document_id}/embedding-job` 查询最新作业状态
- [ ] 5.4 实现 `GET /api/parsed-documents/{parsed_document_id}/embeddings` 分页查询向量列表
- [ ] 5.5 实现 `GET /api/document-chunks/{chunk_id}/embedding` 查询单个 chunk 向量
- [ ] 5.6 实现 `POST /api/parsed-documents/{parsed_document_id}/reembed` 重新向量化
- [ ] 5.7 注册路由到 `api_router`（`app/api/router.py`）
- [ ] 5.8 编写 API 测试：验证 200/202/404/409/412 状态码、权限校验、分页正确性、排序、请求体参数覆盖

## 6. 分块流水线集成

- [ ] 6.1 在 `run_parse_job()` 中分块成功后插入向量化调用（`document_parse_dispatcher.py`），用 `suppress(Exception)` 包裹确保向量化失败不影响分块
- [ ] 6.2 在 `run_rechunk_job()` 中分块成功后插入向量化调用（`document_chunking.py`），新向量化成功后 supersede 旧作业
- [ ] 6.3 在 `run_parse_job` 和 `run_rechunk_job` 中添加 shutdown 状态检查，关闭时跳过向量化
- [ ] 6.4 编写集成测试（Mock 适配器）：验证自动分块后自动向量化、重新分块后自动向量化 + supersede、向量化被禁用时跳过、分块失败时不触发向量化、shutdown 时快速失败

## 7. 关闭收尾

- [ ] 7.1 实现 `mark_incomplete_embedding_jobs_failed_for_shutdown()` 函数（`app/services/document_embedding.py`）
- [ ] 7.2 在 `shutdown.py` 的关闭流程中增加向量化作业收尾调用
- [ ] 7.3 编写关闭收尾测试：验证 queued/running 作业被标记为 `failed` + `error_code=process_shutdown`，succeeded/failed/superseded 作业不被修改

## 8. 文档与验证

- [ ] 8.1 更新 `.env.example` 添加向量化配置项
- [ ] 8.2 更新 `backend/README.md` 添加向量化功能说明和配置指引
- [ ] 8.3 运行 `uv run ruff check .` 和 `uv run ruff format --check .` 通过
- [ ] 8.4 运行 `uv run pytest` 全部通过
- [ ] 8.5 运行 Alembic upgrade/downgrade 循环验证 migration 无残留
- [ ] 8.6 手动 smoke test：配置 DashScope API Key → 上传 PDF → 验证解析 → 验证分块 → 验证向量化作业状态和向量维度