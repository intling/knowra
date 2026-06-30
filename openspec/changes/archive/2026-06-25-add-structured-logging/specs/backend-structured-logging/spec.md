# backend-structured-logging Specification

## Purpose

为 knowra 后端建立一套以 `trace_id` 为核心的结构化日志体系。通过 `contextvars` 实现请求级追踪上下文的自动注入，通过双模式 Formatter 支持开发/生产环境切换，通过 `RotatingFileHandler` 实现文件落盘与滚动，并通过 FastAPI 中间件实现 `X-Trace-ID` 请求头到日志上下文的自动衔接。业务代码仅需通过工厂函数获取 logger 实例，无需每次手动传递 `trace_id`。

## ADDED Requirements

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

系统 SHALL 提供 `get_logger(name)` 工厂函数，返回一个自动向每条日志注入当前 `trace_id` 的 Logger 实例。业务代码无需了解追踪上下文的细节。

#### Scenario: 通过工厂函数获取 logger

- **WHEN** 业务模块调用 `logger = get_logger(__name__)`
- **THEN** 返回的 logger MUST 支持 `debug()`、`info()`、`warning()`、`error()`、`exception()` 方法
- **AND** 每条日志的输出 MUST 自动包含当前请求的 `trace_id`（若无请求上下文则为 `-`）

#### Scenario: 传递额外结构化字段

- **WHEN** 业务代码调用 `logger.info("文件上传完成", extra={"file_name": "notes.pdf", "byte_size": 2048})`
- **THEN** 日志输出 MUST 包含 `trace_id`、`file_name` 和 `byte_size` 字段
- **AND** 日志的 `message` MUST 为 "文件上传完成"

#### Scenario: 无请求上下文时 trace_id 为空占位符

- **WHEN** 日志在 HTTP 请求生命周期之外输出（如应用启动时、后台任务中）
- **THEN** 日志输出的 `trace_id` MUST 为 `-`
- **AND** 该日志 MUST NOT 抛出异常

### Requirement: 双模式日志格式化

系统 SHALL 根据 `LOG_FORMAT` 配置提供两种输出格式：开发友好的彩色可读格式（`console`）和生产环境可解析的 JSON Lines 格式（`json`）。

#### Scenario: console 模式输出

- **WHEN** `LOG_FORMAT` 配置为 `console`
- **THEN** 每条日志 MUST 包含时间戳、日志级别、trace_id、logger 名称和消息
- **AND** 日志级别 MUST 以 ANSI 颜色区分（如 ERROR 红色、WARNING 黄色、INFO 绿色、DEBUG 蓝色）
- **AND** 额外字段（extra）MUST 以 `key=value` 格式内联在消息中

#### Scenario: json 模式输出

- **WHEN** `LOG_FORMAT` 配置为 `json`
- **THEN** 每条日志 MUST 输出为一行完整 JSON 对象
- **AND** JSON MUST 包含 `ts`、`level`、`trace_id`、`logger`、`message` 字段
- **AND** 所有 `extra` 中的字段 MUST 平铺到 JSON 根级别
- **AND** JSON 对象 MUST NOT 跨多行

#### Scenario: debug 模式自动切换

- **WHEN** `debug` 配置为 `true` 且未显式设置 `LOG_FORMAT`
- **THEN** 日志输出格式 MUST 为 `console`
- **WHEN** `debug` 配置为 `false` 且未显式设置 `LOG_FORMAT`
- **THEN** 日志输出格式 MUST 为 `json`

### Requirement: 文件落盘与滚动

系统 SHALL 将日志同时写入文件，并支持基于文件大小的滚动策略，滚动文件数量和单文件大小可通过配置调整。

#### Scenario: 日志写入文件

- **WHEN** 后端应用启动且 `LOG_FILE_PATH` 配置为 `logs/knowra.log` 的父目录存在
- **THEN** 系统 MUST 将日志写入 `logs/knowra.log` 文件
- **AND** 文件日志格式 MUST 与 `LOG_FORMAT` 设置保持一致

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

系统 SHALL 提供 FastAPI 中间件，读取请求头 `X-Trace-ID`，将其注入追踪上下文，并确保响应头中包含相同的 `X-Trace-ID`。

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

系统 SHALL 通过 `Settings` 类（`app/core/config.py`）管理所有日志相关配置项，支持从环境变量和 `.env` 文件读取。

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

系统 SHALL 在 FastAPI 应用创建时自动配置日志系统并注册 Trace 中间件，业务模块无需手动初始化。

#### Scenario: 应用启动时自动配置

- **WHEN** `create_app()` 或 `app` 实例被创建
- **THEN** 日志系统 MUST 完成初始化（包括 handler、formatter 和 logger 层级设置）
- **AND** Trace 中间件 MUST 已注册到 FastAPI 应用
- **AND** 后续路由中的日志调用 MUST 能输出格式化的日志

### Requirement: TraceFilter 全局 trace_id 注入

系统 SHALL 通过 `logging.Filter` 子类（`TraceFilter`）在 root logger 层面自动将 `contextvars` 中的 `trace_id` 注入到每一条 `LogRecord` 上，使**所有**到达 root logger 的日志记录（包括第三方库 SQLAlchemy、uvicorn 等发出的日志）均携带当前请求的 `trace_id`，无需调用方使用 `KnowraLogger`。

#### Scenario: 第三方库日志自动携带 trace_id

- **WHEN** 一个 HTTP 请求被中间件设置 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** SQLAlchemy 在执行查询时发出 `sqlalchemy.engine.Engine` 日志
- **AND** uvicorn 在请求完成时发出 `uvicorn.access` 日志
- **THEN** SQLAlchemy 日志输出 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`
- **AND** uvicorn 日志输出 MUST 包含 `trace_id = "01JFZ8KJ4X2Q3M5N"`

#### Scenario: TraceFilter 不覆盖已有的 trace_id

- **WHEN** `KnowraLogger.process()` 已通过 `extra` 设置 `record.trace_id = "caller-set"`
- **AND** `TraceFilter.filter()` 被调用
- **THEN** `record.trace_id` MUST 保持为 `"caller-set"`，不被覆盖

#### Scenario: 无请求上下文时 TraceFilter 使用占位符

- **WHEN** 日志在 HTTP 请求生命周期之外输出（如应用启动时）
- **AND** `contextvars` 中无 trace_id 值（默认为 `"-"`）
- **THEN** `TraceFilter` MUST 将 `record.trace_id` 设置为 `"-"`
- **AND** 该日志 MUST NOT 抛出异常

### Requirement: 第三方库日志集成

系统 SHALL 在 `configure_logging()` 中整合 SQLAlchemy 和 uvicorn 的日志器，使其日志统一流经 root logger 的 `TraceFilter` 和 Formatter，消除重复输出，确保所有日志格式一致且携带 `trace_id`。

#### Scenario: SQLAlchemy echo 日志不重复输出

- **WHEN** `settings.debug = true` 且 `create_engine(echo=True)` 被调用
- **THEN** SQLAlchemy 内部的 `_add_default_handler()` 添加的 `StreamHandler` MUST 被移除
- **AND** `sqlalchemy.engine` logger 的 `propagate` MUST 为 `True`
- **AND** SQLAlchemy 引擎日志在每个 handler 中 MUST 只输出一次

#### Scenario: SQLAlchemy 日志级别随 debug 切换

- **WHEN** `settings.debug = true`
- **THEN** `sqlalchemy.engine` logger 级别 MUST 为 `INFO`
- **WHEN** `settings.debug = false`
- **THEN** `sqlalchemy.engine` logger 级别 MUST 为 `WARNING`

#### Scenario: uvicorn logger 预注册 TraceFilter

- **WHEN** `configure_logging()` 被调用
- **THEN** `uvicorn`、`uvicorn.access`、`uvicorn.error` logger MUST 各自注册 `TraceFilter` 实例
- **AND** 该 Filter 在 uvicorn 后续调用 `dictConfig()` 时 MUST NOT 被清除

### Requirement: Lifespan 处理器接管 uvicorn 日志

系统 SHALL 通过 FastAPI `lifespan` 上下文管理器，在 uvicorn 完成其内部的 `dictConfig()` 日志初始化之后，移除 uvicorn 的独立 handler 并将 `propagate` 设为 `True`，使 uvicorn 的访问日志和错误日志流向 root logger 的 `TraceFilter` 和 Formatter。

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
