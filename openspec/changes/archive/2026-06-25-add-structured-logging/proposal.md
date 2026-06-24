## Why

knowra 当前日志基础设施几乎为零——后端仅有一行 `logging.basicConfig`，前端完全没有统一的日志模块。随着系统逐步接入文档解析、语义检索、RAG 等复杂流程，当用户报告"上传的文件检索不到"或"回答没有引用来源"时，开发人员无法串联前端操作与后端多个服务之间的调用链，排查问题只能靠猜测。本次变更为前后端分别建立一套以 **trace_id** 为核心的统一日志体系，使一次用户操作从浏览器到数据库的完整链路可以被追踪和关联。

## What Changes

- **后端**：建立基于 Python 标准库 `logging` + `contextvars` 的结构化日志模块，通过 `TraceFilter` 在 root logger 层面自动向**所有**日志（包括 SQLAlchemy、uvicorn 等第三方库发出的日志）注入 `trace_id`，支持控制台（人类可读/JSON 双模式）和文件（带滚动策略）双通道输出。通过 FastAPI `lifespan` 处理器统一接管 uvicorn 日志格式化。
- **前端**：建立基于 TypeScript 的统一日志模块，自动生成 trace_id 并通过 HTTP 头传递给后端，支持控制台彩色输出、内存环形缓冲区，以及 IndexedDB 持久化落盘（总大小受控、滚动清除）。通过工程规范强制所有前端代码使用 `createLogger()` 输出日志，禁止使用原生 `console.*` 方法。Vue 全局错误和未捕获 Promise 拒绝已自动接入日志系统，无需业务代码额外处理。
- **跨端契约**：约定通过 `X-Trace-ID` 请求/响应头传递 trace_id，前端生成、后端读取并透传。

## Capabilities

### New Capabilities

- `backend-structured-logging`: 后端结构化日志能力，包含 trace context 注入、`TraceFilter` 全局 trace_id 注入、结构化 LoggerAdapter、双模式格式化器、文件滚动落盘、第三方库日志集成（SQLAlchemy + uvicorn）、FastAPI lifespan 处理器，以及 Trace 中间件集成。
- `frontend-structured-logging`: 前端结构化日志能力，包含 trace_id 生成与管理、Logger 类（延迟创建模式）、控制台格式化输出、内存环形缓冲区、IndexedDB 持久化与滚动清除、API Client 自动注入 X-Trace-ID 及请求生命周期日志、Vue 全局错误捕获、未捕获 Promise 拒绝捕获、Stores/Views/API Client 业务代码日志接入，以及强制执行规范（禁止使用原生 console.* 方法，强制使用延迟 Logger 创建模式）。

### Modified Capabilities

（无。本次变更不修改已有能力的规格级别行为。）

## Impact

- **后端代码**：`app/core/logging.py`（重构：新增 `TraceFilter`、整合第三方库日志）、`app/core/config.py`（新增日志配置项）、新增 `app/core/trace_context.py`、新增 `app/middleware/trace.py`、`app/main.py`（注册中间件 + lifespan 处理器接管 uvicorn 日志）。
- **前端代码**：新增 `front/src/shared/logger/` 目录（含 types、trace-context、logger、ring-buffer、disk-buffer、formatter、index 等模块）；修改 `front/src/api/client.ts`（自动注入 X-Trace-ID + 请求生命周期日志）、`front/src/main.ts`（调用 `initLogger()` 初始化日志子系统 + 注册 Vue 全局错误处理器 `app.config.errorHandler` + 注册 `window.unhandledrejection` 监听器）；修改 `front/src/stores/user.ts`（用户加载日志）、`front/src/stores/app.ts`（健康检查日志）、`front/src/views/HomeView.vue`（组件挂载/文件操作/上传日志）。
- **配置变更**：后端 `.env.example` 新增 5 个日志配置项（`LOG_LEVEL`、`LOG_FORMAT`、`LOG_FILE_PATH`、`LOG_FILE_MAX_SIZE`、`LOG_FILE_BACKUP_COUNT`）。前端 `.env` 新增 5 个日志配置项（`VITE_LOG_RING_SIZE`、`VITE_LOG_DISK_MAX_SIZE`、`VITE_LOG_FLUSH_SIZE`、`VITE_LOG_CONSOLE_LEVEL`、`VITE_LOG_BUFFER_LEVEL`）。
- **不影响**：不新增或修改数据库表、API 路由契约；不改变现有用户可见工作流。
