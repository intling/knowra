## Context

knowra 后端目前已经完成两层文档模型启动能力：

```text
FastAPI lifespan startup
    |
    v
DocumentModelBootstrapService
    |  检查或下载 Docling artifacts 与 tokenizer 文件
    v
DocumentModelRuntime.start_async()
    |  后台线程加载 Docling converter/pipeline 与 tokenizer 到内存
    v
解析/分块服务复用 runtime.resource
```

但关闭方向还没有同等明确的生命周期。当前 `DocumentModelRuntime.shutdown()` 只对后台预加载线程执行 `join(timeout=0)`，不会等待正在加载的资源收束，不会显式清空已加载 converter/tokenizer 引用，也不会对运行中的解析/分块作业写入中断原因。`backend/README.md` 也已说明，当前 `background_tasks` 调度器在进程重启时可能留下 `running` 作业。

用户现在需要的“没有任何残留”应被拆成可实现、可测试的后端承诺：

- 对可捕获关闭路径，包括 `Ctrl+C`、`SIGTERM`、uvicorn/gunicorn graceful shutdown 和 FastAPI lifespan teardown，执行统一清理。
- 对应用管理的模型对象、后台预加载线程和 job 状态做确定性收尾。
- 对不可捕获的 `SIGKILL`、宿主机崩溃、容器被强制杀死等情况不承诺进程内清理，但文档需要明确边界。

## Goals / Non-Goals

**Goals:**

- 建立后端应用关闭协调层，让 FastAPI lifespan teardown 调用统一 graceful shutdown 流程。
- 扩展 `DocumentModelRuntime`，支持 `shutting_down` 状态、幂等关闭、限时等待预加载线程、释放资源引用和 best-effort 模型内存清理。
- 在关闭期拒绝新的模型相关工作，避免关停过程中继续创建解析或分块作业。
- 在进程退出前，将无法继续完成的 `queued`/`running` 解析与分块作业标记为 `failed`，并写入稳定错误码 `process_shutdown`。
- 保持现有数据库 schema，不新增表或 migration。
- 使用项目结构化日志记录关闭开始、完成、超时、资源清理失败和作业收尾数量。

**Non-Goals:**

- 不处理 `SIGKILL`、宿主机断电、解释器崩溃或容器强制超时后直接杀进程的清理。
- 不实现生产级外部队列、任务租约、分布式锁、多 worker 协调或跨进程 job ownership。
- 不新增前端模型管理页面，不新增用户触发的模型卸载 API。
- 不改变模型文件下载策略，不删除磁盘上的模型 artifacts 或 tokenizer cache。
- 不改变 embedding、检索、RAG 或引用生成能力。

## Decisions

### Decision 1: 由 FastAPI lifespan teardown 驱动统一 shutdown coordinator

新增后端应用关闭协调对象，例如 `ApplicationShutdownCoordinator`，由 `create_app()` 注入到 `app.state`。lifespan `finally` 中调用 coordinator，coordinator 负责按顺序执行：

```text
lifespan teardown
    |
    v
mark application shutting_down
    |
    +--> reject new model-dependent jobs
    |
    +--> DocumentModelRuntime.shutdown(timeout)
    |
    +--> mark queued/running parse jobs failed(process_shutdown)
    |
    +--> mark queued/running chunk jobs failed(process_shutdown)
    |
    v
structured logs + final app state
```

选择理由：

- 复用 ASGI server 已有信号处理。`Ctrl+C` 和 `SIGTERM` 由 uvicorn/gunicorn 转换为 lifespan teardown，不在业务层再注册全局 signal handler，避免与 server 行为冲突。
- 将模型清理和作业收尾放到一个协调层，避免散落在 `main.py`、runtime、解析服务和分块服务中。
- 测试可以通过 `TestClient` 进入和退出 lifespan，验证 teardown 行为。

替代方案：

- 在模块 import 时注册 `signal.signal()`：容易覆盖 uvicorn 的退出管理，也不利于测试，不采用。
- 只在 `DocumentModelRuntime.shutdown()` 中处理所有事情：runtime 不应知道数据库作业模型，不采用。

### Decision 2: `DocumentModelRuntime.shutdown()` 必须幂等、限时、释放引用

runtime 增加明确关闭状态：

- `status == "shutting_down"`：关闭已开始，模型相关请求不可再进入执行路径。
- `component.status == "shutting_down"`：组件正在释放或等待后台加载结束。
- `component.resource is None`：关闭完成后不再持有 Docling converter/tokenizer 引用。

关闭流程：

1. 获取 runtime lock，将 runtime 标记为 shutting down。
2. 如果后台预加载线程还活着，最多等待 `document_model_shutdown_timeout_seconds`。
3. 对已加载资源执行 best-effort cleanup：
   - 如果资源有 `close()`、`shutdown()`、`dispose()` 或 `release()` 方法，按安全顺序调用存在的方法。
   - 如果 `torch` 已导入且 CUDA 可用，调用 CUDA cache 清理；清理失败只记录日志，不阻断关闭。
   - 最后清空 `resource` 引用，允许 Python GC 回收。
4. 记录结构化日志，包含等待耗时、是否超时、清理失败组件和释放的资源数量。

选择理由：

- 关停路径不能无限等待模型 SDK 或后台线程，否则 `Ctrl+C` 会卡住。
- 清空引用是应用层能可靠保证的资源释放边界；第三方库是否立即归还底层显存/内存只能 best-effort。
- 幂等可以避免 TestClient、uvicorn reload 或异常 teardown 重复调用时产生二次错误。

替代方案：

- 强制杀线程：Python 不提供安全线程强杀，会让模型库和解释器状态不可预测，不采用。
- 仅依赖进程退出释放内存：对开发体验和测试不可观测，也不能解决 job 残留，不采用。

### Decision 3: 新请求和后台任务使用共享 shutdown state 做协作式停止

新增轻量 `ApplicationShutdownState`，暴露只读方法或属性供 API 和后台服务检查：

- `is_shutting_down`
- `started_at`
- `reason`

API 层在创建新的 PDF 解析请求或重分块请求前检查该状态。若正在关闭：

- 返回 `503 Service Unavailable`。
- 响应 detail 表达服务正在关闭。
- 不创建新的解析或分块作业。

后台 `run_parse_job()` 和 `DocumentChunkingService` 在进入模型调用前、持久化成功结果前检查该状态。若已关闭：

- 作业标记为 `failed`。
- `error_code` 为 `process_shutdown`。
- `error_message` 表达进程关闭导致作业中断。

选择理由：

- 不能可靠中断正在第三方 SDK 内部执行的同步调用，但可以阻止新任务进入，并在关键边界协作式停止。
- 后台任务即使在关闭窗口内继续运行，也不会在检测到 shutdown 后再写入成功结果。

替代方案：

- 让所有请求等待关闭完成：关闭期不应继续承接耗时模型工作，不采用。
- 把 job 重新排队：当前没有外部队列或租约语义，重新排队会制造重复执行风险，不采用。

### Decision 4: 作业收尾复用现有 `failed` 状态和 `process_shutdown` 错误码

解析作业和分块作业已有 `status`、`error_code`、`error_message`、`finished_at`、`updated_at` 字段。关闭收尾不新增 migration，只更新仍处于 `queued` 或 `running` 的作业：

```text
status        -> failed
error_code    -> process_shutdown
error_message -> Process shut down before the job could finish
finished_at   -> utc_now()
updated_at    -> utc_now()
```

选择理由：

- 复用现有 job 状态模型，前端和 API 已能展示失败状态。
- `process_shutdown` 与 `model_unavailable`、`parse_failed`、`chunking_failed` 区分清楚，便于排查重启和中断。
- 当前文档已声明 `background_tasks` 只适合本地开发和测试，单进程下标记所有 `queued`/`running` 作业符合现阶段部署假设。

替代方案：

- 新增 `cancelled` 或 `interrupted` 状态：需要迁移、API schema 和前端状态适配；现阶段 `failed + error_code` 已能表达原因，不采用。
- 不处理 queued 作业，只处理 running 作业：关停时 queued 作业同样不会被当前进程继续执行，会残留阻塞后续重试，不采用。

### Decision 5: health 保持兼容，只扩展关闭期摘要

`GET /api/health` 继续返回 `200`。如果关闭期间仍能收到 health 请求，`document_models` 中的整体状态和组件状态应表达 `shutting_down`，并保留已有组件诊断字段。这个行为不新增独立 endpoint，也不改变 `/api/health` 的成功状态码。

选择理由：

- health 目前已经承担模型 readiness 摘要，继续沿用最小 API 面。
- 关闭期 health 主要服务本地调试和容器 preStop/探针观察，不应改变业务 API 契约。

替代方案：

- 新增 `/api/health/shutdown`：增加 API 面，但没有必要，不采用。
- shutdown 时让 health 返回 503：会改变现有健康检查契约，且关闭期间 server 未必继续接收请求，不采用。

## Risks / Trade-offs

- 同步 Docling 解析可能正在第三方 SDK 内部执行，无法立即中断 -> 采用限时等待、协作式检查和最终 DB 收尾；文档明确不强杀线程。
- 多 worker 同时运行时，一个 worker 的 shutdown 可能标记另一个 worker 的作业 -> 当前 `background_tasks` 已限定为本地开发和测试；生产外部队列会另起变更设计 ownership/lease。
- best-effort torch/CUDA 清理不保证所有底层 allocator 立即归还显存 -> 清理失败只记录日志；进程退出仍是最终兜底。
- 关闭期标记作业失败可能与后台任务完成存在竞争 -> 后台服务在写成功前检查 shutdown state，并在实现中让 `process_shutdown` 不被后续成功覆盖。
- shutdown timeout 太短会导致日志中出现未完全停止的预加载线程 -> 默认取保守值并允许配置覆盖。

## Migration Plan

1. 新增 OpenSpec delta 和任务清单。
2. 按 TDD 添加 runtime shutdown、lifespan teardown、health shutdown、解析作业收尾、分块作业收尾和关闭期 API fail-fast 测试。
3. 增加关闭配置，例如 `DOCUMENT_MODEL_SHUTDOWN_TIMEOUT_SECONDS`，并写入 `Settings` 与 `.env.example`。
4. 实现 `ApplicationShutdownState` 与 `ApplicationShutdownCoordinator`，接入 FastAPI lifespan。
5. 扩展 `DocumentModelRuntime.shutdown()`，实现幂等状态转换、限时等待和资源 cleanup。
6. 调整解析和分块 API/服务，使其在 shutdown state 下拒绝新任务，并在后台执行边界写入 `process_shutdown`。
7. 更新根 README 和后端 README，说明 graceful shutdown 覆盖范围、不可捕获强杀边界和作业收尾语义。
8. 运行后端 targeted tests、`uv run ruff check .`、`uv run ruff format --check .` 和 `uv run pytest`。

回滚时移除 shutdown coordinator、runtime 扩展、关闭配置和文档说明即可回到当前行为；已写入 `failed/process_shutdown` 的作业是普通失败记录，不需要数据迁移。

## Open Questions

无。首版按单进程 `background_tasks` 假设实现 graceful shutdown；多进程队列、任务租约和可恢复作业作为后续独立变更处理。
