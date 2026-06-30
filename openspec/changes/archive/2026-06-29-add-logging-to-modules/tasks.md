## 1. Service 层 — uploads.py 日志接入

- [x] 1.1 RED：编写 `tests/services/test_upload_service.py` 日志测试，覆盖 `create_upload()` 的 INFO（上传成功）、WARNING（不支持的类型/空文件）、ERROR（存储失败/commit 失败 rollback）日志输出，确认当前无日志导致测试失败
- [x] 1.2 GREEN：在 `app/services/uploads.py` 中引入 `get_logger(__name__)`，在 content type 校验失败、文件写入成功、空文件检测、commit 成功、commit 失败 rollback、存储写入失败等关键路径添加日志
- [x] 1.3 REFACTOR：检查日志字段和级别是否符合 spec 中 `### Requirement: Service 层日志记录` 要求，确保日志调用不影响原有异常抛出逻辑

## 2. Service 层 — users.py 日志接入

- [x] 2.1 RED：编写 `tests/services/test_user_service.py` 日志测试，覆盖 `get_current_user()` 的 DEBUG（用户存在）和 WARNING（用户不存在）日志输出，确认当前无日志导致测试失败
- [x] 2.2 GREEN：在 `app/services/users.py` 中引入 `get_logger(__name__)`，在用户查询成功和 `CurrentUserUnavailableError` 异常前添加日志
- [x] 2.3 REFACTOR：检查日志字段和级别，确保异常抛出逻辑不变

## 3. API 路由层 — uploads.py 日志接入

- [x] 3.1 RED：编写 `tests/api/test_uploads.py` 日志测试，覆盖 `create_upload` 路由的四种异常分支（413/400/500/503）的日志输出，确认当前无日志导致测试失败
- [x] 3.2 GREEN：在 `app/api/routes/uploads.py` 中引入 `get_logger(__name__)`，在每个 `raise HTTPException` 前添加对应级别的日志（WARNING/ERROR）
- [x] 3.3 REFACTOR：确保日志在 HTTPException 抛出之前执行，日志字段包含异常上下文

## 4. API 路由层 — users.py 日志接入

- [x] 4.1 RED：编写 `tests/api/test_users.py` 日志测试，覆盖 `read_current_user` 路由 503 异常分支的日志输出，确认当前无日志导致测试失败
- [x] 4.2 GREEN：在 `app/api/routes/users.py` 中引入 `get_logger(__name__)`，在 `CurrentUserUnavailableError` 捕获处添加 ERROR 级别日志
- [x] 4.3 REFACTOR：确保日志在 HTTPException 抛出之前执行

## 5. API 路由层 — health.py 日志接入

- [x] 5.1 RED：编写 `tests/api/test_health.py` 日志测试，覆盖 `read_health` 正常响应的 DEBUG 日志输出，确认当前无日志导致测试失败
- [x] 5.2 GREEN：在 `app/api/routes/health.py` 中引入 `get_logger(__name__)`，在返回 HealthResponse 前添加 DEBUG 级别日志
- [x] 5.3 REFACTOR：检查日志字段是否包含 `app_name` 和 `environment`

## 6. DB 层 — session.py 日志接入

- [x] 6.1 GREEN：在 `app/db/session.py` 中引入 `get_logger(__name__)`，在 engine 创建后添加 INFO 级别日志，包含脱敏后的 `database_url` 和 `echo` 状态
- [x] 6.2 VERIFY：确认 `database_url` 中的密码已被脱敏（`***`替换），日志格式符合 console/json 模式要求

## 7. DB 层 — init_db.py 日志接入

- [x] 7.1 GREEN：在 `app/db/init_db.py` 中引入 `get_logger(__name__)`，在 `create_all` 执行前后添加 INFO 级别日志
- [x] 7.2 VERIFY：确认 `init_db()` 调用时日志正常输出

## 8. 中间件层 — trace.py 日志接入

- [x] 8.1 RED：编写 `tests/middleware/test_trace_middleware.py` 日志测试，覆盖中间件的 DEBUG 日志（trace_id 生成和复用两种情况），确认当前无日志导致测试失败
- [x] 8.2 GREEN：在 `app/middleware/trace.py` 中引入 `get_logger(__name__)`，在 trace_id 生成（未携带 header）和复用（携带有效 header）时添加 DEBUG 级别日志
- [x] 8.3 REFACTOR：确保日志不影响中间件的 trace_id 设置和响应头注入逻辑

## 9. 质量门禁

- [x] 9.1 运行 `uv run ruff check .` 确保代码风格通过
- [x] 9.2 运行 `uv run ruff format --check .` 确保代码格式通过
- [x] 9.3 运行 `uv run pytest` 确保全部测试通过（包括新增的日志测试和已有测试）
- [x] 9.4 人工抽查：启动应用并触发各 API 端点，观察日志输出是否包含 `trace_id`、模块名和正确的日志级别
