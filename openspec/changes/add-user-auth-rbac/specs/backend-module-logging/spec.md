## MODIFIED Requirements

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

- **WHEN** 用户注册、登录成功、登录失败、退出、修改密码或被管理员调整角色/状态
- **THEN** 系统 SHALL 输出 INFO 或 WARNING 级别结构化日志，包含 `user_id`（未知邮箱登录失败时不含）及操作原因字段
- **AND** 日志 MUST NOT 包含明文密码、会话令牌、令牌哈希或 Cookie 请求头

### Requirement: API 路由层日志记录

所有 API 路由模块 SHALL 在返回非 2xx HTTP 响应之前输出对应级别的日志，使异常响应可被追溯。

#### Scenario: 上传路由异常日志

- **WHEN** `create_upload` 路由捕获 `UploadTooLargeError`
- **THEN** 系统 SHALL 在抛出 413 HTTPException 之前输出 WARNING 级别日志，包含原始文件名和文件大小信息
- **WHEN** 路由捕获 `UploadValidationError`
- **THEN** 系统 SHALL 在抛出 400 HTTPException 之前输出 WARNING 级别日志，包含验证失败原因
- **WHEN** 路由捕获 `UploadStorageError` 或 `UploadMetadataError`
- **THEN** 系统 SHALL 在抛出 500 HTTPException 之前输出 ERROR 级别日志，包含异常详情

#### Scenario: 用户路由异常日志

- **WHEN** 私有接口因缺少或失效会话返回 401
- **THEN** 系统 SHALL 输出 INFO 级别日志，包含请求路径与失败原因，且 MUST NOT 记录 Cookie 值

#### Scenario: 健康检查日志

- **WHEN** `read_health` 路由被调用
- **THEN** 系统 SHALL 输出 DEBUG 级别日志，包含 `app_name` 和 `environment` 字段
