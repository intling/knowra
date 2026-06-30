# backend-module-logging Specification

## Purpose

确保 knowra 后端所有业务模块（Service 层、API 路由层、DB 层、中间件层）均接入已有的结构化日志系统，在关键路径上输出可追溯的日志，消除生产环境排障依赖猜测的现状。

本 spec 在 `backend-structured-logging` spec 已交付的日志基础设施之上，定义各模块**必须**接入日志的行为要求。

## Requirements

### Requirement: Service 层日志记录

所有 Service 层模块 SHALL 通过 `get_logger(__name__)` 获取 logger 实例，并在关键操作路径上输出结构化日志。

#### Scenario: 文件上传全流程日志

- **WHEN** `UploadService.create_upload()` 被调用
- **THEN** 系统 SHALL 在 content type 校验不通过时输出 WARNING 级别日志，包含 `content_type` 和 `allowed_types` 字段
- **AND** 系统 SHALL 在文件写入存储成功后输出 INFO 级别日志，包含 `upload_id`、`byte_size`、`checksum_sha256` 字段
- **AND** 系统 SHALL 在文件大小为 0 时输出 WARNING 级别日志，包含 `upload_id` 字段
- **AND** 系统 SHALL 在数据库 commit 成功后输出 INFO 级别日志，包含 `upload_id` 字段
- **AND** 系统 SHALL 在数据库 commit 失败触发 rollback 时输出 ERROR 级别日志，包含 `upload_id` 和异常信息
- **AND** 系统 SHALL 在存储写入失败时输出 ERROR 级别日志，包含 `storage_key` 和异常信息

#### Scenario: 用户查询日志

- **WHEN** `get_current_user()` 被调用
- **THEN** 系统 SHALL 在查询到用户时输出 DEBUG 级别日志，包含 `user_id` 字段
- **AND** 系统 SHALL 在未查到当前用户时输出 WARNING 级别日志，包含 `default_user_id` 字段

### Requirement: API 路由层日志记录

所有 API 路由模块 SHALL 在返回非 2xx HTTP 响应之前输出对应级别的日志，使异常响应可被追溯。

#### Scenario: 上传路由异常日志

- **WHEN** `create_upload` 路由捕获 `UploadTooLargeError`
- **THEN** 系统 SHALL 在抛出 413 HTTPException 之前输出 WARNING 级别日志，包含原始文件名和文件大小信息
- **WHEN** 路由捕获 `UploadValidationError`
- **THEN** 系统 SHALL 在抛出 400 HTTPException 之前输出 WARNING 级别日志，包含验证失败原因
- **WHEN** 路由捕获 `UploadStorageError` 或 `UploadMetadataError`
- **THEN** 系统 SHALL 在抛出 500 HTTPException 之前输出 ERROR 级别日志，包含异常详情
- **WHEN** 路由捕获 `CurrentUserUnavailableError`
- **THEN** 系统 SHALL 在抛出 503 HTTPException 之前输出 ERROR 级别日志

#### Scenario: 用户路由异常日志

- **WHEN** `read_current_user` 路由捕获 `CurrentUserUnavailableError`
- **THEN** 系统 SHALL 在抛出 503 HTTPException 之前输出 ERROR 级别日志

#### Scenario: 健康检查日志

- **WHEN** `read_health` 路由被调用
- **THEN** 系统 SHALL 输出 DEBUG 级别日志，包含 `app_name` 和 `environment` 字段

### Requirement: DB 层日志记录

DB 层模块 SHALL 在 engine 创建和数据库初始化时输出日志。

#### Scenario: Engine 创建日志

- **WHEN** `session.py` 模块创建 SQLAlchemy engine
- **THEN** 系统 SHALL 输出 INFO 级别日志，包含 `database_url`（脱敏后）和 `echo` 配置状态

#### Scenario: 数据库初始化日志

- **WHEN** `init_db()` 被调用
- **THEN** 系统 SHALL 在 `create_all` 执行前输出 INFO 级别日志
- **AND** 系统 SHALL 在 `create_all` 执行成功后输出 INFO 级别日志

### Requirement: 中间件层日志记录

Trace 中间件 SHALL 在 trace_id 的生成和传递过程中输出 DEBUG 级别日志。

#### Scenario: Trace ID 生成日志

- **WHEN** 请求未携带 `X-Trace-ID` 且中间件生成新的 UUID7
- **THEN** 系统 SHALL 输出 DEBUG 级别日志，包含新生成的 `trace_id`
- **WHEN** 请求携带有效的 `X-Trace-ID`
- **THEN** 系统 SHALL 输出 DEBUG 级别日志，包含该 `trace_id`

### Requirement: 日志级别规范

业务模块 SHALL 遵循统一的日志级别使用规范。

#### Scenario: 日志级别使用

- **WHEN** 记录开发调试信息（如函数进入/退出、中间状态）
- **THEN** 系统 SHALL 使用 DEBUG 级别
- **WHEN** 记录正常业务流程（如操作成功完成、资源创建）
- **THEN** 系统 SHALL 使用 INFO 级别
- **WHEN** 记录可恢复的异常或业务校验不通过（如参数非法、资源不存在）
- **THEN** 系统 SHALL 使用 WARNING 级别
- **WHEN** 记录不可恢复的错误（如数据库提交失败、存储写入失败）
- **THEN** 系统 SHALL 使用 ERROR 级别
