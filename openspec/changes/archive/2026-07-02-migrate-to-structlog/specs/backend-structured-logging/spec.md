# backend-structured-logging — Delta Spec

本 delta spec 记录将自研日志实现迁移至 `structlog` 后，`backend-structured-logging` spec 中发生变化的 requirements。

不变更的 requirements（追踪上下文隔离、文件落盘与滚动、Trace 中间件、TraceFilter 全局 trace_id 注入、第三方库日志集成、Lifespan 处理器接管 uvicorn 日志）行为语义不变，不在本文档中重复。

---

## MODIFIED Requirements

### Requirement: 结构化 Logger 工厂

系统 SHALL 提供 `get_logger(name)` 工厂函数，返回一个基于 `structlog` 的 logger 实例，自动向每条日志注入当前 `trace_id`（通过 `structlog.contextvars.bind_contextvars()` 与 `trace_context` 模块协作）。业务代码无需了解追踪上下文的细节。

#### Scenario: 通过工厂函数获取 logger

- **WHEN** 业务模块调用 `logger = get_logger(__name__)`
- **THEN** 返回的 logger MUST 支持 `debug()`、`info()`、`warning()`、`error()`、`exception()` 方法
- **AND** 每条日志的输出 MUST 自动包含当前请求的 `trace_id`（若无请求上下文则为 `-`）

#### Scenario: 传递额外结构化字段

- **WHEN** 业务代码调用 `logger.info("文件上传完成", file_name="notes.pdf", byte_size=2048)`
- **THEN** 日志输出 MUST 包含 `trace_id`、`file_name` 和 `byte_size` 字段
- **AND** 日志的 `event`（或 `message`）MUST 为 "文件上传完成"

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

系统 SHALL 根据 `LOG_FORMAT` 配置提供两种输出格式：开发友好的彩色可读格式（`console`）和生产环境可解析的 JSON Lines 格式（`json`）。底层由 `structlog` 的 processor 管道实现（`structlog.dev.ConsoleRenderer` 用于 console 模式，`structlog.processors.JSONRenderer` 用于 JSON 模式）。

#### Scenario: console 模式输出

- **WHEN** `LOG_FORMAT` 配置为 `console`
- **THEN** 每条日志 MUST 包含时间戳、日志级别、trace_id、logger 名称和消息
- **AND** 日志级别 MUST 以 ANSI 颜色区分（如 ERROR 红色、WARNING 黄色、INFO 绿色、DEBUG 蓝色）
- **AND** 额外字段（关键字参数传入的上下文）MUST 出现在日志输出中

#### Scenario: json 模式输出

- **WHEN** `LOG_FORMAT` 配置为 `json`
- **THEN** 每条日志 MUST 输出为一行完整 JSON 对象
- **AND** JSON MUST 包含 `timestamp`、`level`、`trace_id`、`logger`、`event` 字段
- **AND** 所有上下文关键字参数传入的字段 MUST 平铺到 JSON 根级别
- **AND** JSON 对象 MUST NOT 跨多行

#### Scenario: debug 模式自动切换

- **WHEN** `debug` 配置为 `true` 且未显式设置 `LOG_FORMAT`
- **THEN** 日志输出格式 MUST 为 `console`
- **WHEN** `debug` 配置为 `false` 且未显式设置 `LOG_FORMAT`
- **THEN** 日志输出格式 MUST 为 `json`

### Requirement: 日志配置

系统 SHALL 通过 `Settings` 类（`app/core/config.py`）管理所有日志相关配置项，支持从环境变量和 `.env` 文件读取。`configure_logging()` SHALL 同时配置标准库 `logging`（handler、filter、文件轮转等底层基础设施）和 `structlog`（processor 管道、renderer 选择）。

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

---

## ADDED Requirements

### Requirement: structlog 上下文绑定

系统 SHALL 支持通过 `structlog` 的 `bind()` 方法在调用链中持久化绑定上下文字段，使后续所有日志调用自动携带绑定字段，无需每次手动传递。

#### Scenario: 在中间件中绑定请求级上下文

- **WHEN** HTTP 请求进入且 `TraceMiddleware` 已设置 `trace_id`
- **AND** 后续中间件或路由调用 `logger.bind(user_id="u_01", tenant_id="t_01")`
- **THEN** 该请求链路中后续所有使用该 bound logger 的日志 MUST 自动包含 `user_id` 和 `tenant_id` 字段

#### Scenario: bound logger 不污染其他请求

- **WHEN** 请求 A 的 logger 绑定了 `user_id="u_A"`
- **AND** 请求 B 的 logger 绑定了 `user_id="u_B"`
- **THEN** 请求 A 的日志 MUST NOT 出现 `user_id="u_B"`
- **AND** 请求 B 的日志 MUST NOT 出现 `user_id="u_A"`

#### Scenario: 解绑上下文

- **WHEN** 业务代码调用 `log = logger.unbind("user_id")`
- **THEN** 之后使用 `log` 输出的日志 MUST NOT 包含 `user_id` 字段
- **AND** 其他已绑定字段（如 `trace_id`）MUST 继续携带

### Requirement: structlog 日志调用规范

所有业务模块 SHALL 使用以下模式输出日志：

- 获取 logger：`from app.core.logging import get_logger` + `logger = get_logger(__name__)`
- 结构化字段：使用关键字参数传递，如 `logger.info("上传完成", file_name="notes.pdf", byte_size=2048)`
- 上下文绑定：`logger.bind(key=value)` 用于在调用链中持久化上下文

#### Scenario: 关键字参数替代 extra 字典

- **WHEN** 业务代码调用 `logger.info("处理完成", user_id="u_01", duration_ms=150)`
- **THEN** 日志输出 MUST 包含 `user_id` 和 `duration_ms` 字段（作为结构化数据，而非嵌入在消息字符串中）
- **AND** 该调用方式 SHALL 通过 Code Review 检查

#### Scenario: 禁止使用 print 和原始 logging.getLogger

- **WHEN** Code Review 发现代码中使用 `print()` 或 `logging.getLogger()` 直接输出日志
- **THEN** Review MUST 拒绝该代码
- **AND** 提示使用 `from app.core.logging import get_logger` 替代
