## 1. 契约与 RED 测试

- [x] 1.1 为 `DocumentModelRuntime.shutdown()` 编写 RED 单元测试，覆盖已加载资源释放、资源清理失败继续关闭、后台预加载线程限时等待、重复 shutdown 幂等和资源引用最终清空；每个测试函数添加中文意图注释。
- [x] 1.2 为应用 lifespan teardown 编写 RED 测试，覆盖 `TestClient` 退出时调用 shutdown coordinator、关闭状态进入 `shutting_down`、结构化日志事件稳定和不覆盖 ASGI server signal handler；每个测试函数添加中文意图注释。
- [x] 1.3 为 `/api/health` 编写 RED 测试，覆盖 graceful shutdown 期间 `document_models.status` 和组件状态返回 `shutting_down`，且不新增独立 health endpoint；每个测试函数添加中文意图注释。
- [x] 1.4 为解析 API 和后台 dispatcher 编写 RED 测试，覆盖关闭期创建解析返回 `503` 且不创建作业、queued/running 解析作业被标记为 `failed/process_shutdown`、已完成解析作业不被覆盖、后台解析在模型调用前和写成功前协作式失败；每个测试函数添加中文意图注释。
- [x] 1.5 为分块 API 和服务编写 RED 测试，覆盖关闭期重新分块返回 `503` 且不创建作业、queued/running 分块作业被标记为 `failed/process_shutdown`、已完成或 superseded 分块作业不被覆盖、分块在 tokenizer/HybridChunker 调用前和写成功前协作式失败；每个测试函数添加中文意图注释。
- [x] 1.6 运行新增 targeted tests，确认它们因缺少 graceful shutdown 行为按预期失败，并在输出红测试代码后停止，提示用户：“红测试已生成，请评审。确认无误后，请回复‘继续’，我将进入绿测试阶段。”

## 2. 关闭协调与配置

- [x] 2.1 在后端配置中新增模型 runtime shutdown timeout 配置，设置有限默认值，并更新配置测试，确保该配置不复用 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 命名空间。
- [x] 2.2 新增 `ApplicationShutdownState`，提供 `is_shutting_down`、`started_at`、`reason` 等只读关闭状态，并覆盖幂等状态转换测试。
- [x] 2.3 新增 `ApplicationShutdownCoordinator`，按顺序标记关闭状态、关闭模型 runtime、收尾解析作业、收尾分块作业，并使用项目结构化日志记录开始、完成、超时和错误诊断。
- [x] 2.4 将 shutdown coordinator 接入 FastAPI lifespan teardown，并通过 `app.state` 注入测试替身和生产实例。

## 3. 模型 Runtime 清理

- [x] 3.1 扩展 `DocumentModelRuntime` 状态模型，支持 runtime 和组件级 `shutting_down` 状态，并让 health 序列化继续兼容已有字段。
- [x] 3.2 实现 `DocumentModelRuntime.shutdown(timeout_seconds=...)` 的幂等关闭、线程限时等待、资源 cleanup hook 调用和资源引用清空。
- [x] 3.3 实现 best-effort 模型内存清理边界，包括可用资源的 `close()`、`shutdown()`、`dispose()`、`release()` hook，以及可用时的 torch/CUDA cache 清理；清理失败只记录结构化日志。
- [x] 3.4 确保 shutdown 期间 `start_async()` 和 `load_once()` 不会重新加载或重新写入 ready resource。

## 4. 解析作业收尾

- [x] 4.1 新增解析作业 shutdown 收尾服务或函数，将 `queued`/`running` 解析作业标记为 `failed`，写入 `error_code=process_shutdown`、`error_message`、`finished_at` 和 `updated_at`。
- [x] 4.2 在解析创建 API 中检查 `ApplicationShutdownState`，关闭期返回 `503 Service Unavailable` 且不创建新作业。
- [x] 4.3 在 `run_parse_job()` 中增加关闭状态协作式检查，确保进入 Docling converter 前和写入成功状态前都能转为 `process_shutdown`。
- [x] 4.4 确保 `process_shutdown` 不会被后续 `parse_failed` 或 `succeeded` 写入覆盖。

## 5. 分块作业收尾

- [x] 5.1 新增分块作业 shutdown 收尾服务或函数，将 `queued`/`running` 分块作业标记为 `failed`，写入 `error_code=process_shutdown`、`error_message`、`finished_at` 和 `updated_at`。
- [x] 5.2 在重新分块 API 中检查 `ApplicationShutdownState`，关闭期返回 `503 Service Unavailable` 且不创建新作业。
- [x] 5.3 在 `DocumentChunkingService` 中增加关闭状态协作式检查，确保进入 tokenizer/HybridChunker 前和写入成功状态前都能转为 `process_shutdown`。
- [x] 5.4 确保 `process_shutdown` 不会被后续 `chunking_failed` 或 `succeeded` 写入覆盖，也不会修改 `succeeded`、`failed`、`superseded` 旧作业。

## 6. 文档与验证

- [x] 6.1 更新 `backend/.env.example`，补充模型 runtime shutdown timeout 配置和注释。
- [x] 6.2 更新根 README 与 `backend/README.md`，说明 `Ctrl+C`、`SIGTERM`、lifespan teardown 的 graceful shutdown 行为、`SIGKILL` 等不可捕获边界、模型资源清理和 `process_shutdown` 作业收尾语义。
- [x] 6.3 运行 runtime、lifespan、health、解析和分块相关 targeted tests，确认本变更覆盖的测试全部通过。
- [x] 6.4 运行后端质量门禁：`uv run ruff check .`、`uv run ruff format --check .` 和 `uv run pytest`。
- [x] 6.5 运行 `openspec status --change "add-graceful-model-shutdown"`，确认变更 apply-ready 且任务状态符合实际进度。
