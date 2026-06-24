# frontend-structured-logging Specification

## Purpose

为 knowra 前端建立一套以 `trace_id` 为核心的统一日志体系。前端在页面加载时生成 UUID7 作为会话级 `trace_id`，通过 `X-Trace-ID` 请求头传递给后端；日志输出到浏览器控制台（彩色格式化）和内存环形缓冲区；缓冲区溢出时异步落盘到 IndexedDB，按总大小上限滚动清除。业务代码通过工厂函数获取 logger 实例，`trace_id` 自动注入，无需手动传递。

## ADDED Requirements

### Requirement: Trace ID 生成与管理

系统 SHALL 在页面加载时生成一个 UUID7 格式的 `trace_id`，保存到 `sessionStorage`，并在整个页面生命周期内保持不变。页面刷新时 `sessionStorage` 中的 `trace_id` 保持不变；关闭标签页后 `sessionStorage` 被清除，下次访问生成新的 `trace_id`。

#### Scenario: 页面加载生成 trace_id

- **WHEN** 用户首次打开 knowra 页面（`sessionStorage` 中没有 `trace_id`）
- **THEN** 系统 MUST 生成一个新的 UUID7 格式字符串
- **AND** 系统 MUST 将该 `trace_id` 保存到 `sessionStorage`

#### Scenario: 页面刷新复用已有 trace_id

- **WHEN** 用户刷新页面（`sessionStorage` 中已有 `trace_id`）
- **THEN** 系统 MUST 复用已有的 `trace_id`，而非生成新值

#### Scenario: trace_id 为 UUID7 格式

- **WHEN** 系统生成 `trace_id`
- **THEN** `trace_id` MUST 是一个符合 UUID 格式（8-4-4-4-12 hex）的字符串
- **AND** `trace_id` 的第 1 个字符 MUST 为 `0`（UUID7 版本标识）

### Requirement: 日志工厂函数

系统 SHALL 提供 `createLogger(module: string)` 工厂函数，返回一个 Logger 实例。Logger 的每条日志自动注入当前 `trace_id` 和模块名。

#### Scenario: 创建 Logger 实例

- **WHEN** 业务模块调用 `const logger = createLogger('stores:user')`
- **THEN** 返回的 Logger MUST 包含 `debug()`、`info()`、`warn()`、`error()` 四个日志方法
- **AND** 每个日志方法的调用 MUST 自动携带当前 `trace_id` 和模块名

#### Scenario: 记录 info 级别日志

- **WHEN** 业务代码调用 `logger.info('用户登录成功', { userId: 'u_123' })`
- **THEN** 控制台 MUST 输出包含 `trace_id`、`stores:user`、`INFO`、`用户登录成功` 和 `userId=u_123` 的格式化内容
- **AND** 该日志条目 MUST 进入环形缓冲区（若 `LOG_BUFFER_LEVEL` ≤ info）

#### Scenario: 记录 error 级别日志

- **WHEN** 业务代码调用 `logger.error('API 请求失败', error, { url: '/api/users' })`
- **THEN** 控制台 MUST 输出包含错误堆栈信息（`error.name`、`error.message`、`error.stack`）的格式化内容
- **AND** 日志条目 MUST 包含 `error.name`、`error.message` 和 `error.stack` 字段
- **AND** 日志条目 MUST 进入环形缓冲区

### Requirement: 控制台格式化输出

系统 SHALL 在浏览器控制台输出带颜色的、人类可读的日志格式。

#### Scenario: 日志包含完整字段信息

- **WHEN** 调用 `logger.info('操作完成', { key: 'value' })`
- **THEN** 控制台输出 MUST 包含时间戳（HH:mm:ss.SSS 格式）、日志级别、trace_id（前 6 位缩写）、模块名和消息
- **AND** 不同日志级别 MUST 使用不同 CSS 样式颜色（INFO 蓝色、WARN 橙色、ERROR 红色、DEBUG 灰色）
- **AND** 额外的 `key=value` 对 MUST 内联在消息中

#### Scenario: debug 级别受 LOG_CONSOLE_LEVEL 控制

- **WHEN** `LOG_CONSOLE_LEVEL` 配置为 `info`
- **AND** 调用 `logger.debug('调试信息')`
- **THEN** 该日志 MUST NOT 输出到控制台

### Requirement: 内存环形缓冲区

系统 SHALL 在内存中维护一个固定大小的环形缓冲区，存储 INFO 及以上级别的日志条目。缓冲区满时，最旧的条目被新条目覆盖。

#### Scenario: 日志进入环形缓冲区

- **WHEN** 调用 `logger.info('操作完成')`（info ≥ `LOG_BUFFER_LEVEL`）
- **THEN** 该日志条目 MUST 被追加到环形缓冲区

#### Scenario: debug 级别不入缓冲区

- **WHEN** 调用 `logger.debug('调试信息')`（debug < `LOG_BUFFER_LEVEL`）
- **THEN** 该日志条目 MUST NOT 进入环形缓冲区

#### Scenario: 环形缓冲区满后覆盖旧条目

- **WHEN** 环形缓冲区当前条目数为 `LOG_RING_SIZE`
- **AND** 新日志条目被写入
- **THEN** 缓冲区 MUST 丢弃最旧的条目
- **AND** 缓冲区条目总数 MUST 保持为 `LOG_RING_SIZE`

#### Scenario: 获取全部缓冲日志

- **WHEN** 调用 `ringBuffer.getAll()`
- **THEN** 返回的数组 MUST 按时间戳升序排列
- **AND** 数组长度 MUST NOT 超过 `LOG_RING_SIZE`

### Requirement: IndexedDB 磁盘持久化

系统 SHALL 在环形缓冲区满时，批量将最旧的日志条目写入 IndexedDB。IndexedDB 中的日志总大小受 `LOG_DISK_MAX_SIZE` 限制，超出时滚动清除最旧的 chunk。

#### Scenario: 缓冲区溢出时批量写入 IndexedDB

- **WHEN** 环形缓冲区条目数达到 `LOG_RING_SIZE`
- **AND** 批量 flush 大小为 `LOG_FLUSH_SIZE`（如 100）
- **THEN** 系统 MUST 将缓冲区中最旧的 `LOG_FLUSH_SIZE` 条日志写入 IndexedDB
- **AND** 写入成功的条目 MUST 从缓冲区中被移除

#### Scenario: IndexedDB 总大小超过上限

- **WHEN** IndexedDB 中所有 chunk 的总大小超过 `LOG_DISK_MAX_SIZE`（如 5 MB）
- **THEN** 系统 MUST 删除最旧的 chunk
- **AND** 重复删除直到总大小 ≤ `LOG_DISK_MAX_SIZE`

#### Scenario: IndexedDB 写入失败时静默降级

- **WHEN** IndexedDB 写入操作抛出异常（如存储被浏览器拒绝）
- **THEN** 系统 MUST 静默捕获异常，不在用户界面抛出错误
- **AND** 失败写入的日志条目 MUST 保留在内存缓冲区中（不丢失）
- **AND** 后续日志操作 MUST 继续正常工作

### Requirement: API Client 自动注入

系统 SHALL 在 API Client 层自动为每个请求注入 `X-Trace-ID` 请求头，不需要调用方手动设置。

#### Scenario: GET 请求自动注入 X-Trace-ID

- **WHEN** 业务代码调用 `apiGet('/api/users/me')`
- **THEN** 发出的 HTTP 请求 MUST 包含 `X-Trace-ID` 头
- **AND** 该头的值 MUST 等于当前 session 的 `trace_id`

#### Scenario: POST 请求自动注入 X-Trace-ID

- **WHEN** 业务代码调用 `apiPostForm('/api/uploads', formData)`
- **THEN** 发出的 HTTP 请求 MUST 包含 `X-Trace-ID` 头
- **AND** 该头的值 MUST 等于当前 session 的 `trace_id`

### Requirement: 全局错误捕获

系统 SHALL 在应用初始化时注册全局错误处理，将 Vue 内部错误和未捕获的 Promise 拒绝自动纳入日志体系。

#### Scenario: Vue 组件错误自动记录

- **WHEN** Vue 组件渲染/更新/生命周期钩子中抛出未经捕获的错误
- **THEN** 系统 MUST 通过 logger 以 error 级别记录该错误
- **AND** 日志 MUST 包含 `trace_id` 和错误堆栈信息

#### Scenario: 未捕获 Promise 拒绝自动记录

- **WHEN** 一个 Promise 被拒绝且没有 `.catch()` 处理器（`onunhandledrejection` 触发）
- **THEN** 系统 MUST 通过 logger 以 error 级别记录该拒绝原因

### Requirement: 前端日志配置

系统 SHALL 通过 Vite 环境变量（`import.meta.env`）管理前端日志相关配置，并提供合理的默认值。

#### Scenario: 默认配置值

- **WHEN** 未设置任何日志相关环境变量
- **THEN** `VITE_LOG_RING_SIZE` MUST 默认为 `500`（内存环形缓冲区条目数）
- **AND** `VITE_LOG_DISK_MAX_SIZE` MUST 默认为 `5242880`（IndexedDB 上限 5 MB）
- **AND** `VITE_LOG_FLUSH_SIZE` MUST 默认为 `100`（批量写入条目数）
- **AND** `VITE_LOG_CONSOLE_LEVEL` MUST 默认为 `debug`（控制台最低输出级别）
- **AND** `VITE_LOG_BUFFER_LEVEL` MUST 默认为 `info`（缓冲区最低写入级别）

#### Scenario: 环境变量覆盖默认值

- **WHEN** 环境变量 `VITE_LOG_RING_SIZE=1000`
- **THEN** 环形缓冲区最大条目数 MUST 为 1000
