## Why

knowra 当前日志基础设施几乎为零——后端仅有一行 `logging.basicConfig`，前端完全没有统一的日志模块。随着系统逐步接入文档解析、语义检索、RAG 等复杂流程，当用户报告"上传的文件检索不到"或"回答没有引用来源"时，开发人员无法串联前端操作与后端多个服务之间的调用链，排查问题只能靠猜测。本次变更为前后端分别建立一套以 **trace_id** 为核心的统一日志体系，使一次用户操作从浏览器到数据库的完整链路可以被追踪和关联。

## What Changes

- **后端**：建立基于 Python 标准库 `logging` + `contextvars` 的结构化日志模块，自动向每条日志注入 `trace_id`，支持控制台（人类可读/JSON 双模式）和文件（带滚动策略）双通道输出。
- **前端**：建立基于 TypeScript 的统一日志模块，自动生成 trace_id 并通过 HTTP 头传递给后端，支持控制台彩色输出、内存环形缓冲区，以及 IndexedDB 持久化落盘（总大小受控、滚动清除）。
- **跨端契约**：约定通过 `X-Trace-ID` 请求/响应头传递 trace_id，前端生成、后端读取并透传。

## Capabilities

### New Capabilities

- `backend-structured-logging`: 后端结构化日志能力，包含 trace context 注入、结构化 LoggerAdapter、双模式格式化器、文件滚动落盘，以及与 FastAPI 中间件的集成。
- `frontend-structured-logging`: 前端结构化日志能力，包含 trace_id 生成与管理、Logger 类、控制台格式化输出、内存环形缓冲区，以及 IndexedDB 持久化与滚动清除。

### Modified Capabilities

（无。本次变更不修改已有能力的规格级别行为。）

## Impact

- **后端代码**：`app/core/logging.py`（重构）、`app/core/config.py`（新增日志配置项）、新增 `app/core/trace_context.py`、新增 `app/middleware/trace.py`、`app/main.py`（注册中间件）。
- **前端代码**：新增 `front/src/shared/logger/` 目录（含 types、trace-context、logger、ring-buffer、disk-buffer、formatter、index 等模块）；修改 `front/src/api/client.ts`（自动注入 X-Trace-ID）、`front/src/main.ts`（初始化日志 + 全局错误处理）。
- **配置变更**：后端 `.env.example` 新增 5 个日志配置项（`LOG_LEVEL`、`LOG_FORMAT`、`LOG_FILE_PATH`、`LOG_FILE_MAX_SIZE`、`LOG_FILE_BACKUP_COUNT`）。前端 `.env` 新增 5 个日志配置项（`VITE_LOG_RING_SIZE`、`VITE_LOG_DISK_MAX_SIZE`、`VITE_LOG_FLUSH_SIZE`、`VITE_LOG_CONSOLE_LEVEL`、`VITE_LOG_BUFFER_LEVEL`）。
- **不影响**：不新增或修改数据库表、API 路由契约；不改变现有用户可见工作流。
