## Why

当前后端已经在 FastAPI lifespan 中启动文档模型 bootstrap 和异步内存预加载，但进程收到 `Ctrl+C`、`SIGTERM` 或应用生命周期结束时，只做了非阻塞线程引用释放，未明确卸载已加载的 Docling converter、tokenizer，也未为运行中的解析/分块作业写入可诊断的中断状态。

这会让开发和部署环境在重启、手动中断或容器停止时出现模型资源释放不确定、后台任务仍处于 `running`、后续请求误判作业仍在执行等残留问题，影响“接入资料 -> 解析内容 -> 分块与索引”的核心链路恢复能力。

## What Changes

- 新增后端 graceful shutdown 能力，统一处理应用生命周期结束时的模型 runtime 停止、资源释放和结构化日志。
- 在文档模型 runtime 中新增显式 shutdown 状态转换：停止接受新的预加载/模型使用、等待后台预加载线程在限定时间内结束、释放已加载资源引用，并尽力触发 Python/torch/CUDA 等可用清理钩子。
- 明确信号触发路径：`Ctrl+C`、`SIGTERM` 等由 ASGI server 触发 FastAPI lifespan teardown；应用 teardown 必须执行同一套模型清理逻辑，不额外绕过 uvicorn/gunicorn 的信号管理。
- 为运行中的文档解析作业和文档分块作业增加进程关闭收尾语义：进程退出前将当前进程内仍处于 `queued`/`running` 且无法继续完成的作业标记为 `failed`，并写入稳定错误码和可诊断错误信息。
- 更新健康检查摘要，使 shutdown 期间的模型 readiness 能表达 `shutting_down` 或等价不可服务状态，避免新请求误入模型路径。
- 更新 README 和 `.env.example`，说明 graceful shutdown 行为、超时配置、开发环境 `Ctrl+C` 行为和生产容器停止建议。
- 不新增用户可触发的模型管理 API，不新增前端页面，不引入外部队列或多进程协调机制。

## Capabilities

### New Capabilities

- `backend-runtime-lifecycle`: 覆盖后端应用生命周期、信号驱动的 graceful shutdown、模型 runtime 清理、关闭期 readiness 和结构化日志要求。

### Modified Capabilities

- `document-parsing`: 增加进程关闭期间解析作业的中断收尾要求，避免解析作业永久残留在 `queued`/`running`。
- `document-chunking`: 增加进程关闭期间分块作业的中断收尾要求，避免分块作业永久残留在 `queued`/`running`。

## Impact

- 后端应用入口：调整 FastAPI lifespan teardown，接入统一 shutdown coordinator。
- 后端服务：扩展 `DocumentModelRuntime` 的 shutdown 语义，新增资源释放钩子、状态保护和结构化日志。
- 数据库作业状态：复用现有 `failed` 状态、`error_code` 和 `error_message` 字段，不新增表或 migration。
- API 行为：`GET /api/health` 继续返回 `200`，但 `document_models` 摘要需要在关闭期表达不可服务状态；模型相关请求在关闭期应快速失败，不创建新作业。
- 配置：新增可选关闭超时配置，例如模型预加载线程等待时长和作业收尾开关；敏感信息不涉及。
- 文档：更新根 README、后端 README 和 `.env.example` 中的模型生命周期与本地/生产停止说明。
- 验证：需要覆盖 runtime shutdown 单元测试、lifespan teardown 测试、解析/分块作业收尾测试、health shutdown 摘要测试，以及后端 ruff/pytest 门禁。
