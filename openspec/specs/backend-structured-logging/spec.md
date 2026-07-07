# backend-structured-logging Specification

## Purpose

为 knowra 后端建立一套以 `trace_id` 为核心的结构化日志体系。通过 `contextvars` 实现请求级追踪上下文的自动注入，基于 `structlog` processor 管道实现双模式输出（console 人类可读 / file JSON Lines），通过 `RotatingFileHandler` 实现文件落盘与滚动，并通过 FastAPI 中间件实现 `X-Trace-ID` 请求头到日志上下文的自动衔接。文件日志始终输出标准 JSON Lines 格式，确保下游日志平台可直接解析。业务代码仅需通过工厂函数获取 logger 实例并通过关键字参数传递结构化字段，无需每次手动传递 `trace_id`。

## Requirements

### Requirement: 追踪上下文隔离

系统 SHALL 基于 `contextvars` 提供请求级别的追踪上下文，使同一请求处理链路上的所有日志自动携带同一个 `trace_id`，且不同请求之间的追踪上下文互不干扰。

#### Scenario: 同一请求内日志携带相同 trace_id

- **WHEN** 一个 HTTP 请求被中间件设置 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** 路由处理函数调用 `logger.info("处理上传")`
- **AND** 服务层函数调用 `logger.debug("保存文件")`
- **THEN** 路由处理函数输出的日志 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** 服务层函数输出的日志 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`

#### Scenario: 不同请求间追踪上下文隔离

- **WHEN** 同时有两个并发请求 A 和 B 正在处理
- **AND** 请求 A 的 `trace_id = "01JFZ8AAAAAA"`
- **AND** 请求 B 的 `trace_id = "01JFZ8BBBBBB"`
- **THEN** 请求 A 产生的日志 MUST NOT 出现 `trace_id = "01JFZ8BBBBBB"`
- **AND** 请求 B 产生的日志 MUST NOT 出现 `trace_id = "01JFZ8AAAAAA"`

### Requirement: 结构化 Logger 工厂

系统 SHALL 提供 `get_logger(name)` 工厂函数，返回一个基于 `structlog` 的 logger 实例，通过 `structlog` processor 管道（`_trace_id_injector`）自动向每条日志注入当前 `trace_id`。业务代码无需了解追踪上下文的细节。

#### Scenario: 通过工厂函数获取 logger

- **WHEN** 业务模块调用 `logger = get_logger(__name__)`
- **THEN** 返回的 logger MUST 是 `structlog.BoundLogger` 或其 lazy proxy 实例
- **AND** 返回的 logger MUST 支持 `debug()`、`info()`、`warning()`、`error()`、`exception()` 方法
- **AND** 每条日志的输出 MUST 自动包含当前请求的 `trace_id`（若无请求上下文则为 `-`）

#### Scenario: 传递额外结构化字段（关键字参数）

- **WHEN** 业务代码调用 `logger.info("文件上传完成", file_name="notes.pdf", byte_size=2048)`
- **THEN** 日志输出 MUST 包含 `trace_id`、`file_name` 和 `byte_size` 字段
- **AND** 日志的 `event` 字段 MUST 为 "文件上传完成"
- **AND** 该调用方式 SHALL 通过 Code Review 检查

#### Scenario: 上下文绑定后自动继承

- **WHEN** 业务代码调用 `log = logger.bind(user_id="u_01")`
- **AND** 之后调用 `log.info("操作完成")`
- **THEN** 日志输出 MUST 包含 `user_id="u_01"` 字段
- **AND** 该字段在后续所有使用 `log` 的调用中自动携带

#### Scenario: 无请求上下文时 trace_id 为空占位符

- **WHEN** 日志在 HTTP 请求生命周期之外输出（如应用启动时、后台任务中）
- **THEN** 日志输出的 `trace_id` MUST 为 `-`
- **AND** 该日志 MUST NOT 抛出异常

### Requirement: 双模式日志格式化

系统 SHALL 根据 `LOG_FORMAT` 配置提供两种 console 输出格式：开发友好的彩色可读格式（`console`）和生产环境可解析的 JSON Lines 格式（`json`）。底层由 `structlog` 的 processor 管道实现。控制台输出由 `LOG_FORMAT` 决定；文件日志 ALWAYS 使用 JSON Lines 格式（`JSONRenderer`），确保下游日志平台可直接解析。

#### Scenario: console 模式控制台输出

- **WHEN** `LOG_FORMAT` 配置为 `console`
- **THEN** 控制台每条日志 MUST 包含时间戳、日志级别、trace_id、logger 名称和消息
- **AND** 日志级别 MUST 以 ANSI 颜色区分（如 ERROR 红色、WARNING 黄色、INFO 绿色、DEBUG 蓝色）
- **AND** 额外字段（关键字参数传入的上下文）MUST 出现在日志输出中
- **AND** 日志级别 MUST NOT 被填充空白对齐（`pad_level=False`），消息 MUST NOT 被填充到固定宽度（`pad_event_to=0`），确保输出紧凑可读

#### Scenario: json 模式控制台输出

- **WHEN** `LOG_FORMAT` 配置为 `json`
- **THEN** 控制台每条日志 MUST 输出为一行完整 JSON 对象
- **AND** JSON MUST 包含 `timestamp`、`level`、`trace_id`、`logger`、`event` 字段
- **AND** 所有上下文关键字参数传入的字段 MUST 平铺到 JSON 根级别

#### Scenario: 文件日志始终为 JSON Lines

- **WHEN** 日志写入文件（不论 `LOG_FORMAT` 配置为何值）
- **THEN** 每条日志 MUST 输出为一行完整 JSON 对象
- **AND** JSON MUST 包含 `timestamp`、`level`、`trace_id`、`logger`、`event` 字段
- **AND** 所有上下文关键字参数传入的字段 MUST 平铺到 JSON 根级别
- **AND** 中文等非 ASCII 字符 MUST 以原文字符输出（`ensure_ascii=False`），不得转义为 `\uXXXX`

#### Scenario: debug 模式自动切换

- **WHEN** `debug` 配置为 `true` 且未显式设置 `LOG_FORMAT`
- **THEN** console 输出格式 MUST 为 `console`
- **AND** 文件输出 MUST 为 JSON Lines
- **WHEN** `debug` 配置为 `false` 且未显式设置 `LOG_FORMAT`
- **THEN** console 输出格式 MUST 为 `json`
- **AND** 文件输出 MUST 为 JSON Lines

### Requirement: 文件落盘与滚动

系统 SHALL 将日志写入文件，文件格式始终为 JSON Lines。支持基于文件大小的滚动策略，滚动文件数量和单文件大小可通过配置调整。

#### Scenario: 日志写入文件

- **WHEN** 后端应用启动且 `LOG_FILE_PATH` 配置为 `logs/knowra.log` 的父目录存在
- **THEN** 系统 MUST 将日志写入 `logs/knowra.log` 文件
- **AND** 文件日志格式 MUST 为 JSON Lines（`{"key": "value", ...}` 每行一个对象）

#### Scenario: 日志文件达到上限后滚动

- **WHEN** `logs/knowra.log` 文件大小达到 `LOG_FILE_MAX_SIZE`（如 10 MB）
- **THEN** 系统 MUST 将当前文件重命名为 `logs/knowra.log.1`
- **AND** 后续日志写入新的 `logs/knowra.log` 文件
- **AND** 已有 `logs/knowra.log.1` 重命名为 `logs/knowra.log.2`，以此类推

#### Scenario: 滚动文件超过保留数量

- **WHEN** `LOG_FILE_BACKUP_COUNT` 配置为 5
- **AND** `logs/knowra.log.5` 已存在且新一轮滚动发生
- **THEN** 系统 MUST 删除 `logs/knowra.log.5`

#### Scenario: 日志路径父目录自动创建

- **WHEN** `LOG_FILE_PATH` 配置为 `logs/subdir/knowra.log` 且 `logs/subdir/` 目录不存在
- **THEN** 系统 MUST 自动创建父目录
- **AND** 系统 MUST NOT 因目录不存在而抛出异常或跳过文件日志

### Requirement: Trace 中间件

系统 SHALL 提供 FastAPI 中间件，读取请求头 `X-Trace-ID`，将其注入追踪上下文（`contextvars`），并确保响应头中包含相同的 `X-Trace-ID`。TraceMiddleware MUST 位于中间件栈最外层，确保 `set_trace_id()` 在同一个 asyncio 任务中执行，使所有子中间件通过 contextvar 继承看到 trace_id。

#### Scenario: 请求携带有效 X-Trace-ID

- **WHEN** 请求头 `X-Trace-ID` 为非空 UUID 格式字符串
- **THEN** 中间件 MUST 将该值设置为当前请求的 `trace_id`
- **AND** 响应头 MUST 包含相同的 `X-Trace-ID`

#### Scenario: 请求未携带 X-Trace-ID

- **WHEN** 请求头中不包含 `X-Trace-ID`
- **THEN** 中间件 MUST 生成一个新的 UUID7 作为 `trace_id`
- **AND** 响应头 MUST 包含该新生成的 `X-Trace-ID`

#### Scenario: 请求携带空白 X-Trace-ID

- **WHEN** 请求头 `X-Trace-ID` 为空字符串
- **THEN** 中间件 MUST 生成一个新的 UUID7 作为 `trace_id`（等同于未携带）

### Requirement: 日志配置

系统 SHALL 通过 `Settings` 类（`app/core/config.py`）管理所有日志相关配置项，支持从环境变量和 `.env` 文件读取。`configure_logging()` SHALL 同时配置标准库 `logging`（handler、filter、文件轮转等底层基础设施）和 `structlog`（processor 管道、renderer 选择）。

#### Scenario: 控制台与文件独立 formatter

- **WHEN** `configure_logging()` 被调用
- **THEN** 控制台 handler MUST 使用由 `LOG_FORMAT` 决定的 renderer（console 或 JSON）
- **AND** 文件 handler MUST 使用独立的 `JSONRenderer` renderer
- **AND** 两个 handler 的 `foreign_pre_chain` MUST 包含相同的处理器链以确保非 structlog 日志字段一致

#### Scenario: 默认配置值

- **WHEN** 未设置任何日志相关环境变量
- **THEN** `LOG_LEVEL` MUST 默认为 `INFO`
- **AND** `LOG_FORMAT` MUST 默认为 `console`（当 `debug=true`）或 `json`（当 `debug=false`）
- **AND** `LOG_FILE_PATH` MUST 默认为 `logs/knowra.log`
- **AND** `LOG_FILE_MAX_SIZE` MUST 默认为 `10485760`（10 MB）
- **AND** `LOG_FILE_BACKUP_COUNT` MUST 默认为 `5`

#### Scenario: 从环境变量读取

- **WHEN** 环境变量 `LOG_LEVEL=DEBUG`、`LOG_FILE_PATH=logs/app.log`、`LOG_FILE_MAX_SIZE=5242880`
- **THEN** Settings 实例的对应属性 MUST 反映这些值

### Requirement: 应用入口集成

系统 SHALL 在 FastAPI 应用创建时自动配置日志系统并注册 Trace 中间件，业务模块无需手动初始化。`configure_logging()` MUST 在 `db/session.py` 等导入时会产生日志的模块之前执行，确保 structlog 已配置完毕。

#### Scenario: 应用启动时自动配置

- **WHEN** `app` 实例被创建（`app = create_app()`）
- **THEN** 日志系统 MUST 在导入会产生日志的模块之前完成 structlog 配置
- **AND** Trace 中间件 MUST 已注册到 FastAPI 应用
- **AND** 后续路由中的日志调用 MUST 能输出格式化的日志
- **AND** "数据库引擎已创建" 等模块导入级日志 MUST 以统一的 structlog 格式输出

#### Scenario: 中间件注册顺序确保 trace_id 传播

- **WHEN** TraceMiddleware 被添加到 FastAPI 应用
- **THEN** TraceMiddleware MUST 是最后注册的中间件（即中间件栈最外层）
- **AND** 所有内层中间件（CORSMiddleware、RequestLoggingMiddleware）输出的日志 MUST 携带正确的 trace_id

### Requirement: TraceFilter 全局 trace_id 注入

系统 SHALL 通过 `logging.Filter` 子类（`TraceFilter`）在 root logger 层面自动将 `contextvars` 中的 `trace_id` 注入到每一条 `LogRecord` 上，使**所有**到达 root logger 的日志记录（包括第三方库 SQLAlchemy、uvicorn、docling 等发出的日志）均携带当前请求的 `trace_id`，无需调用方使用 structlog logger。

#### Scenario: 第三方库日志自动携带 trace_id

- **WHEN** 一个 HTTP 请求被中间件设置 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** SQLAlchemy 在执行查询时发出 `sqlalchemy.engine.Engine` 日志
- **AND** uvicorn 在请求完成时发出 `uvicorn.access` 日志
- **AND** docling 在文档转换时发出 `docling.*` 日志
- **THEN** SQLAlchemy 日志输出 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** uvicorn 日志输出 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** docling 日志输出 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`

#### Scenario: TraceFilter 不覆盖已有的 trace_id

- **WHEN** structlog processor 已通过 `event_dict` 设置了 `trace_id = "caller-set"`
- **AND** `TraceFilter.filter()` 被调用
- **THEN** `record.trace_id` MUST 保持为 `"caller-set"`，不被覆盖

#### Scenario: 无请求上下文时 TraceFilter 使用占位符

- **WHEN** 日志在 HTTP 请求生命周期之外输出（如应用启动时）
- **AND** `contextvars` 中无 trace_id 值（默认为 `"-"`）
- **THEN** `TraceFilter` MUST 将 `record.trace_id` 设置为 `"-"`
- **AND** 该日志 MUST NOT 抛出异常

### Requirement: 第三方库日志统一格式化

系统 SHALL 在 `ProcessorFormatter` 的 `foreign_pre_chain` 中提取非 structlog 日志记录（SQLAlchemy、uvicorn、docling 等第三方库的 `LogRecord`）的 level、timestamp、logger name，使其事件字典与 structlog 日志结构一致，从而通过相同的 renderer 渲染为统一格式。

#### Scenario: SQLAlchemy 日志格式统一

- **WHEN** SQLAlchemy 引擎输出日志（如 `BEGIN`、`SELECT`、`ROLLBACK`）
- **THEN** 日志 MUST 包含 `timestamp`、`level`、`logger`、`event`、`trace_id` 字段
- **AND** 输出格式 MUST 与 structlog 日志完全一致

#### Scenario: docling 日志格式统一

- **WHEN** docling 在文档转换过程中输出日志（如 "Going to convert document batch..."）
- **THEN** 日志 MUST 包含 `timestamp`、`level`、`logger`、`event`、`trace_id` 字段
- **AND** 输出格式 MUST 与 structlog 日志完全一致

### Requirement: Uvicorn 日志配置接管

系统 SHALL 在 `configure_logging()` 中替换 uvicorn 的默认 `LOGGING_CONFIG` 为一个仅设 `propagate=True` 的最小配置，使 uvicorn 的 `dictConfig()` 调用变为空操作。这确保 uvicorn 启动消息（"Started server process"、"Waiting for application startup" 等）在 `Server.run()` 阶段就统一流经 root logger 的 `ProcessorFormatter` 和 `TraceFilter`。

#### Scenario: 替换 LOGGING_CONFIG 后 uvicorn 启动消息格式统一

- **WHEN** `configure_logging()` 被调用
- **THEN** `uvicorn.config.LOGGING_CONFIG` MUST 被替换为一个仅含 `propagate=True` 的最小化配置
- **AND** uvicorn logger（`uvicorn`、`uvicorn.access`、`uvicorn.error`）MUST 已被预配置为 `propagate=True` 且已添加 `TraceFilter`
- **AND** uvicorn 的 `dictConfig()` 调用 MUST 不再覆盖这些设置

#### Scenario: uvicorn 启动消息携带统一格式

- **WHEN** uvicorn 输出 "Started server process [N]"
- **AND** uvicorn 输出 "Waiting for application startup."
- **AND** uvicorn 输出 "Application startup complete."
- **THEN** 以上每条消息 MUST 以统一的 structlog console 格式输出（包含 timestamp、level、logger 等字段）
- **AND** 以上每条消息 MUST NOT 以 uvicorn 原生格式输出（如 "INFO:     Started server process ..."）

### Requirement: Lifespan 处理器双重保险

系统 SHALL 通过 FastAPI `lifespan` 上下文管理器，在 uvicorn 完成其内部的日志初始化之后再次清除 uvicorn 的独立 handler 并将 `propagate` 设为 `True`，作为 `LOGGING_CONFIG` 替换机制的双重保险。

#### Scenario: lifespan 启动后 uvicorn 日志流入 root

- **WHEN** FastAPI 应用启动完成（lifespan 已执行）
- **THEN** `uvicorn.access` logger 的 `handlers` MUST 为空列表
- **AND** `uvicorn.access` logger 的 `propagate` MUST 为 `True`
- **AND** `uvicorn.error` logger 的 `handlers` MUST 为空列表
- **AND** `uvicorn.error` logger 的 `propagate` MUST 为 `True`

#### Scenario: uvicorn 访问日志携带 trace_id

- **WHEN** 一个 HTTP 请求完成且 uvicorn 输出访问日志（如 `"GET /api/health HTTP/1.1" 200`）
- **THEN** 该日志 MUST 通过 root logger 的 Formatter 输出
- **AND** 日志中 MUST 包含正确的 `trace_id`（由 TraceFilter 注入）

### Requirement: structlog 日志调用规范

所有业务模块 SHALL 使用以下模式输出日志：

- 获取 logger：`from app.core.logging import get_logger` + `logger = get_logger(__name__)`
- 事件消息：使用固定、稳定的字符串描述发生了什么，如 `logger.info("上传完成", ...)`
- 结构化字段：所有动态值 MUST 使用关键字参数传递，如 `logger.info("上传完成", file_name="notes.pdf", byte_size=2048)`
- 禁止使用 `%s` / `%d` 等位置参数格式化——structlog 会将其捕获为 `positional_args`，导致日志不可读
- 禁止使用 f-string、`str.format()` 或字符串拼接把动态值写入事件消息
- 禁止使用 `extra={...}` 字典传递字段；字段 MUST 直接作为 keyword arguments 传入
- 上下文绑定：`logger.bind(key=value)` 用于在调用链中持久化上下文

#### Scenario: 使用关键字参数传递动态字段

- **WHEN** 业务代码调用 `logger.info("处理完成", user_id="u_01", duration_ms=150)`
- **THEN** 日志输出 MUST 包含 `user_id` 和 `duration_ms` 字段（作为结构化数据，而非嵌入在消息字符串中）
- **AND** 日志的 `event` 字段 MUST 保持为固定字符串 `"处理完成"`
- **AND** 该调用方式 SHALL 通过 Code Review 检查

#### Scenario: 禁止混用不同日志字段写法

- **WHEN** Code Review 发现业务代码使用 `logger.info("处理完成: user_id=%s", user_id)`、`logger.info(f"处理完成: {user_id}")`、`logger.info("处理完成: {}".format(user_id))` 或 `logger.info("处理完成", extra={"user_id": user_id})`
- **THEN** Review MUST 拒绝该代码
- **AND** 提示使用 `logger.info("处理完成", user_id=user_id)` 形式替代
- **AND** 对应测试或静态检查 SHOULD 覆盖这类禁止写法，避免后续重新引入

#### Scenario: 禁止绕过项目 logger

- **WHEN** Code Review 发现代码中使用 `print()`、`logging.getLogger()` 或 `logging.basicConfig()` 直接输出日志
- **THEN** Review MUST 拒绝该代码
- **AND** 提示使用 `from app.core.logging import get_logger` 获取项目 logger
