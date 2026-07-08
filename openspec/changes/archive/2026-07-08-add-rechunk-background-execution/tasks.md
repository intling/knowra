# Tasks: 补全重新分块后台执行链路

## 阶段一：测试准备（RED）

- [x] **T1.1** 为 `execute_queued_job()` 编写单元测试
  - 正常路径：对 QUEUED job 成功执行分块，验证 supersede_previous=True
  - 边界情况：不调用 `_create_job()`
  - 测试文件：`backend/tests/services/test_document_chunking_service.py`

- [x] **T1.2** 为 `run_rechunk_job` 编写单元测试
  - 正常路径：加载 QUEUED job → RUNNING → 解析 → 分块 → SUCCEEDED
  - 边界情况：job 已非 QUEUED 时幂等返回
  - 异常处理：原始文件缺失 → FAILED
  - 异常处理：解析抛错 → FAILED，不传播异常
  - 异常处理：shutdown → FAILED，不调用 parser/chunker
  - 依赖注入：使用注入的 session_factory 和 parser
  - 测试文件：`backend/tests/services/test_document_chunking_service.py`

- [x] **T1.3** 为 API 端点新增 dispatcher 调用编写集成测试
  - 正常路径：POST /rechunk → 202 → job 状态从 queued 变为 succeeded（通过测试注入的同步执行器）
  - 回归：409 冲突检测不变
  - 回归：503（shutdown / tokenizer loading / tokenizer scope）
  - 回归：原始文件不可用
  - 测试文件：`backend/tests/api/test_document_chunking.py`

- [x] **T1.4** 为移除 `rechunk()` 编写回归测试确认无调用方
  - 搜索全代码库确认 `rechunk()` 无外部调用
  - 搜索全代码库确认 `DeferredOriginalFileDocument` 无外部引用
  - 搜索全代码库确认 `_parse_original_file()` 无外部调用

> **暂停点：** 红测试已生成，请评审。确认无误后回复「继续」，进入阶段二。

## 阶段二：实现（GREEN）

- [x] **T2.1** 在 `DocumentChunkingService` 上新增 `execute_queued_job()` 方法
  - 文件：`backend/app/services/document_chunking.py`
  - 委托 `_run_job(job=job, ..., supersede_previous=True)`
  - 不创建新 job

- [x] **T2.2** 实现 `run_rechunk_job` 后台执行函数
  - 文件：`backend/app/services/document_chunking.py`
  - 签名：`run_rechunk_job(job_id, *, session_factory=None, parser=None, upload_storage_root=None, model_readiness=None, shutdown_state=None)`
  - 流程：加载 job → 检查 QUEUED → 检查 shutdown → 重新解析 → execute_queued_job → 错误处理
  - 支持依赖注入（与 `run_parse_job` 一致的模式）
  - 使用结构化日志（`logger.info("重新分块开始", job_id=...)` 等）

- [x] **T2.3** 实现 `RechunkDispatcher` 调度器
  - 文件：`backend/app/services/document_chunking.py`
  - 结构复制 `BackgroundTasksParseJobDispatcher`

- [x] **T2.4** 在 `rechunk_parsed_document` API 端点接入 dispatcher
  - 文件：`backend/app/api/routes/document_chunking.py`
  - 新增 `background_tasks: BackgroundTasks` 参数
  - 在 `create_queued_rechunk_job()` 后调用 `RechunkDispatcher(background_tasks).enqueue(job.id)`

- [x] **T2.5** 移除废弃代码
  - 移除 `DocumentChunkingService.rechunk()` 方法
  - 移除 `DocumentChunkingService._parse_original_file()` 方法
  - 移除 `DeferredOriginalFileDocument` 类
  - 移除 `DocumentChunkOriginalFileUnavailableError` 类
  - 移除 `DocumentChunkingService` 构造函数中的 `upload_storage` 参数（仅被 `_parse_original_file` 使用）
  - 更新 `__init__` 的 docstring 或类型注解（如有）

- [x] **T2.6** 更新工厂函数 `make_document_chunking_service()`
  - 文件：`backend/app/services/document_parse_dispatcher.py`
  - 移除 `upload_storage` 参数传递（不再需要）
  - 移除 `DocumentChunkOriginalFileUnavailableError` 等不再需要的 import

> **暂停点：** 实现完成，请评审。确认无误后回复「继续」，进入阶段三。

## 阶段三：验证（REFACTOR + 回归）

- [x] **T3.1** 运行后端 lint 和格式检查
  ```bash
  cd backend && uv run ruff check . && uv run ruff format --check .
  ```

- [x] **T3.2** 运行后端全量测试
  ```bash
  cd backend && uv run pytest
  ```

- [x] **T3.3** 运行前端验证（确认无回归）
  ```bash
  cd front && npm run lint && npm run test && npm run build
  ```

- [x] **T3.4** 代码审查：确认 `run_initial_chunking` 路径行为不变
  - parse 完成后自动分块仍正常触发
  - `make_document_chunking_service()` 工厂函数参数正确

- [x] **T3.5** 代码审查：shutdown 收尾路径覆盖
  - `mark_incomplete_chunk_jobs_failed_for_shutdown()` 覆盖 rechunk 创建的 QUEUED/RUNNING job
  - API 层 shutdown 拒绝仍生效

- [x] **T3.6** 如有必要，更新 `openspec/specs/document-chunking/spec.md` 主 spec（sync delta）
