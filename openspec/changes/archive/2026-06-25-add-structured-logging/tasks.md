## 1. 后端追踪上下文

- [x] 1.1 为 `trace_context.py` 编写红测试：验证 `TraceContext.set_trace_id()` / `get_trace_id()` 的基本读写功能
- [x] 1.2 为 `trace_context.py` 编写红测试：验证并发场景下不同协程的追踪上下文隔离性
- [x] 1.3 实现 `app/core/trace_context.py`：封装 `contextvars.ContextVar`，提供 `set_trace_id()` 和 `get_trace_id()` 接口
- [x] 1.4 验证 trace_context 测试转为绿色

## 2. 后端日志配置

- [x] 2.1 为 `config.py` 日志配置项编写红测试：验证新增配置项（`LOG_LEVEL`、`LOG_FORMAT`、`LOG_FILE_PATH`、`LOG_FILE_MAX_SIZE`、`LOG_FILE_BACKUP_COUNT`）的默认值和环境变量读取
- [x] 2.2 在 `app/core/config.py` 的 `Settings` 类中新增 5 个日志配置项
- [x] 2.3 更新 `.env.example` 添加日志配置项说明
- [x] 2.4 验证 config 测试转为绿色

## 3. 后端结构化 Logger

- [x] 3.1 为结构化 Logger 编写红测试：验证 `get_logger()` 返回的 logger 输出的日志自动携带 `trace_id`（有上下文时）或 `-`（无上下文时）
- [x] 3.2 为双模式 Formatter 编写红测试：验证 `console` 模式输出包含 ANSI 颜色码和 `key=value` 格式
- [x] 3.3 为双模式 Formatter 编写红测试：验证 `json` 模式输出为单行有效 JSON，`extra` 字段平铺在根级别
- [x] 3.4 为文件日志 handler 编写红测试：验证日志写入文件、文件轮转触发和备份数量控制
- [x] 3.5 重构 `app/core/logging.py`：实现 `KnowraLogger`（`LoggerAdapter` 子类）、`ConsoleFormatter`（console 模式）、`JsonFormatter`（json 模式）、`configure_logging()`（整合 console handler + RotatingFileHandler）
- [x] 3.6 验证 logging 测试转为绿色

## 4. 后端 Trace 中间件

- [x] 4.1 为 Trace 中间件编写红测试：验证请求携带有效 `X-Trace-ID` 时，中间件将其设置为 trace_id 且响应头包含相同值
- [x] 4.2 为 Trace 中间件编写红测试：验证请求缺少 `X-Trace-ID` 时，中间件生成新 UUID7
- [x] 4.3 为 Trace 中间件编写红测试：验证请求携带空白 `X-Trace-ID` 时，中间件生成新 UUID7
- [x] 4.4 实现 `app/middleware/__init__.py` 和 `app/middleware/trace.py`：FastAPI 中间件，读取/补发 `X-Trace-ID`，注入 `TraceContext`
- [x] 4.5 验证中间件测试转为绿色

## 5. 后端应用入口集成

- [x] 5.1 修改 `app/main.py`：在 `create_app()` 中注册 Trace 中间件，确保中间件在所有路由之前执行
- [x] 5.2 为集成后的完整链路编写集成测试：验证从请求进入到响应的完整日志链路（`X-Trace-ID` → `TraceContext` → logger 输出）
- [x] 5.3 验证集成测试转为绿色，运行 `uv run ruff check .` 和 `uv run pytest` 全部通过

## 6. 前端类型定义

- [x] 6.1 实现 `front/src/shared/logger/types.ts`：定义 `LogLevel`、`LogRecord`、`LoggerOptions` 等 TypeScript 类型和接口
- [x] 6.2 编写类型定义的单元测试：验证 `LogRecord` 类型约束（必填字段 `ts`、`level`、`trace_id`、`module`、`message`）

## 7. 前端 Trace ID 生成与管理

- [x] 7.1 为 TraceManager 编写红测试：验证首次调用生成 UUID7 格式字符串并写入 sessionStorage
- [x] 7.2 为 TraceManager 编写红测试：验证 sessionStorage 已有值时复用已有 trace_id
- [x] 7.3 为 TraceManager 编写红测试：验证生成的 UUID7 首字符为 `0`（版本标识）且长度符合 UUID 规范
- [x] 7.4 实现 `front/src/shared/logger/trace-context.ts`：`TraceManager` 类，封装 UUID7 生成 + sessionStorage 读写
- [x] 7.5 验证 TraceManager 测试转为绿色

## 8. 前端 Logger 核心

- [x] 8.1 为 Logger 类编写红测试：验证 `createLogger('module:name')` 返回包含 `debug/info/warn/error` 方法的实例
- [x] 8.2 为 Logger 类编写红测试：验证日志自动注入 `trace_id` 和 `module`，无需调用方手动传递
- [x] 8.3 为 Logger 类编写红测试：验证 `logger.error()` 自动提取 `Error.name`、`Error.message`、`Error.stack`
- [x] 8.4 为 Logger 类编写红测试：验证 `LOG_CONSOLE_LEVEL` 低于当前级别的日志不输出到控制台
- [x] 8.5 实现 `front/src/shared/logger/logger.ts`：`Logger` 类和 `createLogger()` 工厂函数
- [x] 8.6 验证 Logger 测试转为绿色

## 9. 前端控制台格式化

- [x] 9.1 为 formatter 编写红测试：验证格式化输出包含时间戳、级别缩写、trace_id 前缀、模块名、消息
- [x] 9.2 为 formatter 编写红测试：验证不同日志级别使用不同 CSS 颜色（ERROR 红、WARN 橙、INFO 蓝、DEBUG 灰）
- [x] 9.3 实现 `front/src/shared/logger/formatter.ts`：`formatLogRecord()` 函数和 `consoleStyles` 颜色映射
- [x] 9.4 验证 formatter 测试转为绿色

## 10. 前端环形缓冲区

- [x] 10.1 为 RingBuffer 编写红测试：验证追加日志条目，`getAll()` 返回按时间排序的条目列表
- [x] 10.2 为 RingBuffer 编写红测试：验证缓冲区满 (`LOG_RING_SIZE`) 时丢弃最旧条目
- [x] 10.3 为 RingBuffer 编写红测试：验证 debug 级别（低于 `LOG_BUFFER_LEVEL`）的条目不被追加
- [x] 10.4 为 RingBuffer 编写红测试：验证 `flush(count)` 返回最旧 count 条并从缓冲区移除
- [x] 10.5 实现 `front/src/shared/logger/ring-buffer.ts`：`RingBuffer` 类，固定大小数组 + writeIndex
- [x] 10.6 验证 RingBuffer 测试转为绿色

## 11. 前端 IndexedDB 磁盘缓冲区

- [x] 11.1 为 DiskBuffer 编写红测试：验证 `write(chunk)` 将日志批量写入 IndexedDB
- [x] 11.2 为 DiskBuffer 编写红测试：验证总大小超过 `LOG_DISK_MAX_SIZE` 时删除最旧 chunk
- [x] 11.3 为 DiskBuffer 编写红测试：验证 IndexedDB 写入失败时静默降级，不抛异常
- [x] 11.4 为 DiskBuffer 编写红测试：验证 `readAll()` 按时间顺序返回全部持久化日志
- [x] 11.5 实现 `front/src/shared/logger/disk-buffer.ts`：`DiskBuffer` 类，封装 IndexedDB 的 chunk 存储和滚动逻辑
- [x] 11.6 验证 DiskBuffer 测试转为绿色

## 12. 前端日志模块统一导出

- [x] 12.1 实现 `front/src/shared/logger/index.ts`：统一导出 `createLogger`、`TraceManager`、`RingBuffer`，导出初始化函数 `initLogger()`
- [x] 12.2 为 `initLogger()` 编写测试：验证初始化函数完成 TraceManager 创建、Logger 工厂配置和全局配置注入

## 13. 前端 API Client 集成

- [x] 13.1 为 API Client 的 X-Trace-ID 注入编写红测试：验证 `apiGet` 和 `apiPostForm` 调用时请求头包含 `X-Trace-ID`
- [x] 13.2 修改 `front/src/api/client.ts`：在 `apiGet` 和 `apiPostForm` 中自动注入 `X-Trace-ID` 请求头
- [x] 13.3 验证 API Client 测试转为绿色

## 14. 前端应用入口集成

- [x] 14.1 修改 `front/src/main.ts`：注册 `app.config.errorHandler`（Vue 全局错误 → logger.error）
- [x] 14.2 修改 `front/src/main.ts`：注册 `window.onunhandledrejection`（未捕获 Promise → logger.error）
- [x] 14.3 编写集成测试：模拟 Vue 组件错误，验证被 logger 捕获并正确记录
- [x] 14.4 验证集成测试转为绿色，运行 `npm run lint`、`npm run test`、`npm run build` 全部通过

## 15. 文档更新

- [x] 15.1 更新 `backend/README.md`：添加日志配置项说明（LOG_LEVEL、LOG_FORMAT、LOG_FILE_PATH 等）
- [x] 15.2 更新 `front/README.md`：添加日志模块目录结构和使用示例
- [x] 15.3 检查并更新根目录 `README.md` 中与日志相关的启动说明（如有需要）

## 5.5 后端全局 trace_id 注入与第三方库集成

- [x] 5.5.1 在 `app/core/logging.py` 中新增 `TraceFilter(logging.Filter)` 类：在 `filter()` 中从 `contextvars` 读取 `trace_id` 并注入到 `LogRecord`，若已有值则保留
- [x] 5.5.2 在 `configure_logging()` 中为 root logger 注册 `TraceFilter`（`root.addFilter(TraceFilter())`），并清除已有 filters（`root.filters.clear()`）以保证幂等性
- [x] 5.5.3 在 `configure_logging()` 中清理 SQLAlchemy echo 引入的 handler：移除 `sqlalchemy.engine` / `sqlalchemy.engine.Engine` / `sqlalchemy.pool` logger 上的 handler，设置 `propagate=True`，根据 debug 设置级别
- [x] 5.5.4 在 `configure_logging()` 中为 `uvicorn` / `uvicorn.access` / `uvicorn.error` logger 预注册 `TraceFilter`（uvicorn dictConfig 不会清除 filters）
- [x] 5.5.5 修改 `ConsoleFormatter.format()` 和 `JsonFormatter.format()`：trace_id 取值改为 `getattr(record, "trace_id", None) or get_trace_id()`，作为 TraceFilter 的兜底

## 5.6 后端 Lifespan 处理器集成 uvicorn

- [x] 5.6.1 修改 `app/main.py`：新增 `lifespan` 异步上下文管理器，在其中移除 `uvicorn` / `uvicorn.access` / `uvicorn.error` 的 handler、清除 filters、设置 `propagate=True`、重新注册 `TraceFilter`
- [x] 5.6.2 将 `lifespan` 传入 `FastAPI(lifespan=lifespan)`
- [x] 5.6.3 修复 `.env` 和 `.env.example` 中日志配置 section 的注释格式（`---` → `# ---`）

## 5.7 代码质量验证

- [x] 5.7.1 运行 `uv run ruff check .` 和 `uv run ruff format .`，修复所有 lint 错误
- [x] 5.7.2 运行 `uv run pytest`，确认全部 73 个测试通过

## 14.5 前端日志系统强制执行规范

- [x] 14.5.1 在 `config.yaml` 开发治理规则中新增前端日志系统说明条款：明确 `initLogger()` 自动初始化、`createLogger()` 自动注入 trace_id、全局错误自动捕获、API Client 自动注入 X-Trace-ID
- [x] 14.5.2 在 `specs/frontend-structured-logging/spec.md` 中新增 "前端日志系统强制执行" Requirement：禁止 console.log 等原生方法、Vue 全局错误已自动接入、未捕获 Promise 拒绝已自动接入、API Client 已自动注入 X-Trace-ID
- [x] 14.5.3 验证前端代码实现与规范一致：`main.ts` 已调用 `initLogger()` 并注册 `app.config.errorHandler` 和 `window.unhandledrejection`；`client.ts` 已通过 `commonHeaders()` 自动注入 `X-Trace-ID`

## 14.6 前端业务代码日志集成

- [x] 14.6.1 在 `stores/user.ts` 中集成 `createLogger("stores:user", getRingBuffer())`：记录用户加载开始、成功（含 userId/displayName）和失败
- [x] 14.6.2 在 `stores/app.ts` 中集成 `createLogger("stores:app", getRingBuffer())`：记录健康检查开始、成功和失败
- [x] 14.6.3 在 `views/HomeView.vue` 中集成 `createLogger("views:Home", getRingBuffer())`：记录组件挂载、文件选择、文件上传成功/失败
- [x] 14.6.4 在 `api/client.ts` 中集成 `createLogger("api:client", getRingBuffer())`：记录 GET/POST 请求发送（debug）、成功（info）、网络错误（error）和非 2xx 状态（warn），含 path/status/duration
- [x] 14.6.5 更新关联测试文件的 mock（`client.test.ts`、`user.test.ts`、`app.test.ts`、`HomeView.test.ts`、`health.test.ts`、`uploads.test.ts`、`users.test.ts`）：mock `../shared/logger` 模块以避免 `initLogger()` 前置依赖
- [x] 14.6.6 运行 `npm run lint`、`npm run test`、`npm run build`，确认全部通过（61 测试，0 lint 错误，build 成功）
