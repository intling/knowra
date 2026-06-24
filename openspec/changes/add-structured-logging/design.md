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
