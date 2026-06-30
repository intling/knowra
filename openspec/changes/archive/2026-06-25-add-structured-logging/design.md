## Context

knowra 当前后端日志仅有一行 `logging.basicConfig`（`app/core/logging.py`，约 9 行），输出固定格式文本，无结构化字段、无 trace_id、无文件落盘。前端完全没有日志模块——`console.log` 零星散落在组件和 store 中，无统一格式、无级别控制、无持久化。

随着 knowra 逐步构建文档解析、语义检索和 RAG 能力，系统调用链将变长：一个用户问题可能触发前端路由 → API 请求 → 中间件 → 查询改写 → 向量检索 → 重排 → LLM 生成 → 引用溯源。如果不能通过 trace_id 串联这些环节的日志，当用户反馈"检索结果不符预期"时，开发人员无从定位问题发生在哪一层。

## Goals / Non-Goals

**Goals:**
- 前端生成页面级 trace_id（UUID7），通过 HTTP 头 `X-Trace-ID` 传递给后端
- 后端读取 `X-Trace-ID` 头（缺失时自动补发），通过 `contextvars` 注入到所有后续日志
- 后端日志支持控制台输出（开发友好彩色格式 / 生产 JSON Lines 格式，通过配置切换）和文件落盘（`RotatingFileHandler`，路径与大小可配）
- 前端日志支持控制台输出（彩色格式）、内存环形缓冲区（固定条目数），以及 IndexedDB 持久化落盘（总大小受控、滚动清除）
- 前端 API Client 自动在请求头注入 `trace_id`
- 日志模块高度封装，业务代码仅需 `import` + 工厂函数调用，无需每次手动传递 `trace_id`

**Non-Goals:**
- 不实现 OpenTelemetry 集成或 span/parent-span 分布式追踪
- 不实现前端日志上报到后端 API（保留后续扩展空间）
- 不修改现有 API 路由的响应契约
- 不增加新的外部依赖（Python 端仅使用标准库；前端仅使用浏览器 API）
- 不实现日志采样、日志分析或告警

## Decisions

### 决策 1：后端使用 `contextvars` 而非 `threading.local`

**选择**：使用 Python 标准库 `contextvars.ContextVar` 存储 trace_id。

**理由**：FastAPI 在 asyncio 事件循环中运行，单个线程可能交错处理多个请求。`threading.local` 在 `await` 切换协程时会被其他请求污染。`contextvars` 是 PEP 567 引入的标准库机制，每个 asyncio Task 有独立的上下文副本，天然隔离，不需要锁。

**替代方案**：
- `threading.local` — 在 async 下不安全，拒绝。
- 手动在每个函数签名中传递 `trace_id` — 侵入性太强，不符合"高度封装"目标，拒绝。

### 决策 2：后端使用 `logging.LoggerAdapter` 而非自定义 Logger 类

**选择**：使用 Python 标准库 `logging.LoggerAdapter` 自动向每条日志的 `extra` 字段注入 `trace_id`。

**理由**：`LoggerAdapter` 是标准库的内置机制，与所有现有 logging 配置（Handler、Formatter、Filter）兼容。第三方库（SQLAlchemy、uvicorn 等）的日志也能通过 `logging.getLogger()` 层级继承格式化配置。

**替代方案**：
- 自定义 Logger 子类 — 与标准库生态兼容性差。
- `loguru` — 额外依赖，非标准库，过度引入。
- `structlog` — 理念很好但与 knowra 当前极简的日志状态差距太大，成本高。

### 决策 3：双模式 Formatter 通过配置切换

**选择**：后端提供两种 Formatter 实现，通过 `LOG_FORMAT` 配置项切换。

- `console`：带 ANSI 颜色的可读格式（开发环境默认）
- `json`：JSON Lines 格式（生产环境，`debug=false` 时默认）

**理由**：开发时需要快速扫读日志，颜色和缩进比 JSON 更友好。生产环境需要结构化日志以便 `jq`、日志收集器（如 Fluentd、Vector）解析。

**替代方案**：始终 JSON — 开发体验差。始终文本 — 生产环境不可解析。两者都支持是公认最佳实践。

### 决策 4：文件落盘使用标准库 `RotatingFileHandler`

**选择**：使用 `logging.handlers.RotatingFileHandler` 实现文件滚动。

**理由**：无需引入第三方文件轮转依赖（如 `concurrent-log-handler`），标准库方案覆盖 knowra 单进程场景完全足够。若后续需要多进程部署，可替换为 `logging.handlers.WatchedFileHandler` 或外部日志收集器。

配置项：
- `LOG_FILE_PATH`：日志文件路径（默认 `logs/knowra.log`）
- `LOG_FILE_MAX_SIZE`：单文件最大字节数（默认 10 MB）
- `LOG_FILE_BACKUP_COUNT`：保留历史文件数（默认 5）

### 决策 5：前端 trace_id 生成使用 UUID7

**选择**：生成 UUID7（时间排序版本）而非 UUID4（随机版本）。

**理由**：UUID7 的前 48 位是 Unix 毫秒时间戳，天然按时间排序。在日志中按时间顺序排列时，UUID7 的排序结果与时间戳排序一致，便于肉眼扫描和 grep 过滤。

**替代方案**：
- UUID4 — 完全随机，无法排序，查找时需要额外时间戳字段。
- 自增 ID — 无全局唯一性保证。

### 决策 6：前端 trace_id 生命周期为页面级

**选择**：页面加载时生成一次 trace_id，通过 `sessionStorage` 持久化，页面刷新时保持不变。

**理由**：用户的一次使用会话（从打开到关闭/刷新）在逻辑上是一个连续的追踪单元。页面刷新是同一个会话，trace_id 应保持一致。关闭标签页后 sessionStorage 自动清除，下次打开生成新 trace_id。

**替代方案**：
- 路由级 trace_id — 导致同一用户操作（如上传后刷新列表）被拆分到两个 trace，概念割裂。
- localStorage 跨会话保持 — 一个 trace_id 覆盖多天，失去区分会话的意义。

### 决策 7：前端落盘使用 IndexedDB 而非 localStorage

**选择**：使用 IndexedDB 作为日志持久化层。

**理由**：
- IndexedDB 是异步 API，不会阻塞主线程（localStorage 同步写入可能卡 UI）
- IndexedDB 容量远大于 localStorage（几百 MB vs 5-10 MB）
- 日志系统只占用总上限（默认 5 MB）的一小部分，不影响其他功能

**落盘策略**：
- 内存环形缓冲区固定 N 条（默认 500），超出时批量 flush M 条（默认 100）到 IndexedDB
- IndexedDB 按 chunk 存储（每个 chunk ~1 MB），总大小超过 `LOG_DISK_MAX_SIZE` 时删除最旧 chunk
- 逻辑上形成双层环：内存环 + 磁盘环

### 决策 8：日志级别分两层控制

**选择**：前端区分 console 输出级别和 buffer 写入级别。

- `LOG_CONSOLE_LEVEL`（默认 `debug`）：低于此级别的日志不输出到控制台
- `LOG_BUFFER_LEVEL`（默认 `info`）：低于此级别的日志不入环形缓冲区（因此也不会落盘）

**理由**：debug 日志量大（"组件渲染"、"API 请求发出"等），适合开发调试但不应占满珍贵的缓冲区和落盘空间。INFO 及以上（用户操作、业务事件、错误）才是诊断问题时的关键信息。

## Risks / Trade-offs

- **[风险] 日志文件占用磁盘空间** → 通过 `LOG_FILE_MAX_SIZE` 和 `LOG_FILE_BACKUP_COUNT` 控制总上限（最大 60 MB with defaults）。IndexedDB 同样由 `LOG_DISK_MAX_SIZE` 控制。
- **[风险] 前端 IndexedDB 写入失败（如隐私模式）** → 磁盘写入操作包裹 try/catch，失败时静默降级（仅内存缓冲区，不影响应用正常运行）。
- **[风险] 日志模块引入后现有 `console.log` 调用不统一** → 非本次变更范围。后续逐步迁移业务代码中的 `console.log`，不在本次一次性替换。
- **[权衡] 前端不支持日志上报到后端** → 当前缺少的服务端日志收集能力，但"高度封装的前端日志模块"是它的必要前提。环形缓冲区 + IndexedDB 的设计使其可以在后续以最小改动对接上报 API。

## Open Questions

（无。探索阶段已与用户确认所有关键设计决定。）

### 决策 9：使用 `logging.Filter` 实现全局 trace_id 注入

**选择**：新增 `TraceFilter(logging.Filter)` 类，通过 root logger 的 `addFilter()` 注册，在 `filter()` 方法中直接从 `contextvars` 读取 `trace_id` 并注入到 `LogRecord.trace_id`。

**理由**：
- `LoggerAdapter`（KnowraLogger）只能覆盖业务代码主动调用 `get_logger()` 的场景，无法覆盖第三方库（SQLAlchemy、uvicorn）内部直接使用 `logging.getLogger()` 发出的日志。
- `logging.Filter` 作用于 logger 层级，**所有**到达该 logger 的 `LogRecord` 都会经过 `filter()` 方法。将 `TraceFilter` 注册在 root logger 上，即可覆盖整个应用的全部日志输出。
- `filter()` 中先检查 `record.trace_id` 是否已由 `KnowraLogger.process()` 设置，避免覆盖调用方显式传入的值。

**替代方案**：
- 仅依赖 `Formatter.format()` 中调用 `get_trace_id()` — 可以工作但 Formatter 的职责是格式化，从 contextvars 读取数据属于"上下文注入"而非"格式化"，职责不清晰。TraceFilter 将注入逻辑与格式化逻辑分离。
- 在 `Formatter.format()` 中 fallback 调用 `get_trace_id()` — 作为兜底机制保留（当 TraceFilter 未覆盖到的边缘场景）。

**结合使用**：`TraceFilter`（注入） + `Formatter` fallback（兜底）两层保障。TraceFilter 覆盖所有到达 root 的日志，Formatter fallback 确保即使 Filter 被跳过也能拿到值。

### 决策 10：通过 FastAPI lifespan 处理器集成 uvicorn 日志

**选择**：使用 FastAPI `lifespan` 上下文管理器，在 uvicorn 启动并完成其内部 `dictConfig()` 日志初始化之后，移除 uvicorn logger 的独立 handler 并设置 `propagate=True`。

**理由**：
- **启动时序问题**：`configure_logging()` 在 `create_app()` 中被调用（模块导入时执行），但 uvicorn 的 `dictConfig()` 在 uvicorn 服务器启动时（`uvicorn.run()` 或 `uvicorn.Config.configure_logging()`）才被调用，晚于应用代码的日志配置。在 uvicorn 配置自己的日志之前对 uvicorn loggers 做任何修改都会被覆盖。
- **lifespan 的执行时机**：FastAPI `lifespan` 在 uvicorn 完成所有初始化（包括日志配置）之后、开始接收请求之前执行。在此处清理 uvicorn handler 并设置 `propagate=True`，可以确保 uvicorn 日志最终流向 root logger。
- **`propagate=True` 的效果**：uvicorn 的 `dictConfig` 默认设置 `propagate=False`，这意味着 uvicorn 的日志不会向上传播到 root logger。设为 `True` 后，uvicorn 日志经 root 的 TraceFilter 注入 `trace_id` 再经 Formatter 格式化输出。

**替代方案**：
- 完全替换 uvicorn 的 `LOGGING_CONFIG` — 侵入性强，需要维护完整的 uvicorn 日志配置副本，升级 uvicorn 时可能引入不一致。
- 仅依赖 `configure_logging()` 中预注册 TraceFilter — 只能让 uvicorn 的 handler 看到 trace_id，但 uvicorn 仍然用自己的 Formatter 输出，格式不统一。lifespan 方案使 uvicorn 日志完全流经应用 Formatter。

**注**：`configure_logging()` 中仍保留对 uvicorn logger 预注册 TraceFilter 的操作，作为 lifespan 执行前的兜底（覆盖应用启动早期阶段的 uvicorn 日志）。lifespan 执行后会完全接管 uvicorn 日志的格式化。

### 决策 11：业务代码使用延迟 Logger 创建模式

**选择**：业务模块（stores、components、API client）在模块顶层 export 一个惰性 getter 函数（如 `function log()`），在首次调用时才创建 logger 实例，而非在模块导入时立即创建。

**理由**：
- **初始化时序**：`initLogger()` 在 `main.ts` 中调用，而业务模块的 import 发生在模块解析阶段，可能早于 `main.ts` 的执行。若在 import 时调用 `getRingBuffer()`，会因 `initLogger()` 尚未执行而抛出异常。
- **lazy 模式的实现**：每个模块定义一个模块级 `_logger` 变量（初始为 `null`），以及一个 `log()` 函数，在首次调用时才执行 `createLogger("module:name", getRingBuffer())` 并缓存结果。
- **运行时安全**：logger 的首次实际调用总是发生在用户交互或生命周期钩子中（点击按钮、`onMounted`、`store action` 等），此时 `main.ts` 已执行完毕，`initLogger()` 已确保 `getRingBuffer()` 可用。

**替代方案**：
- 在模块 import 时直接创建 logger — 时序不安全，`getRingBuffer()` 可能抛出异常。
- 将所有 logger 实例放在 `main.ts` 中并通过 props/provide 传递 — 侵入性强，违背"业务代码仅需 import + 工厂函数调用"的设计目标。
