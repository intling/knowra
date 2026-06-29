## Context

knowra 后端的结构化日志基础设施（`app/core/logging.py`、`app/core/trace_context.py`、`app/middleware/trace.py`）已在 `backend-structured-logging` spec 中完整交付。`configure_logging()` 在应用启动时自动配置 root logger、双模式 Formatter、文件滚动、TraceFilter 全局 trace_id 注入，以及 SQLAlchemy/uvicorn 的日志整合。

然而，当前仅 `app/main.py` 在应用启动阶段使用了日志，其余所有业务模块（7 个文件）均未接入日志系统。根据 AGENTS.md 规则——"所有代码模块 MUST 使用本项目内建的结构化日志系统输出日志"——这是一个合规性缺口，也是可观测性的短板。

前端模块已全面接入日志系统（`api/client.ts`、`stores/app.ts`、`stores/user.ts`、`views/HomeView.vue`），本变更**仅涉及后端**。

## Goals / Non-Goals

**Goals:**
- 为 7 个后端模块补充结构化日志调用，使全链路可追踪
- 统一日志级别使用规范（DEBUG/INFO/WARNING/ERROR）
- 确保每个异常分支在返回 HTTP 错误前有对应日志
- 保持现有测试通过，新增日志相关测试用例

**Non-Goals:**
- 不修改日志基础设施（`logging.py`、`trace_context.py`、`trace.py` 的核心逻辑）
- 不在前端新增日志（前端已全覆盖）
- 不修改 `configure_logging()` 或日志配置项
- 不引入新的日志依赖

## Decisions

### 1. 日志接入方式：`get_logger(__name__)`

每个模块通过 `from app.core.logging import get_logger` 导入，在模块顶部实例化 `logger = get_logger(__name__)`。这种方式：

- 自动注入 `trace_id`（通过 `KnowraLogger` 适配器）
- **同时**通过 root logger 的 `TraceFilter` 二次保障——即使模块不使用 `extra` 传参，LogRecord 也会被 Filter 注入 `trace_id`
- 模块名（`__name__`）自动成为 logger name，便于按模块过滤日志
- 无需修改 `configure_logging()`，无需手动配置 handler

**为何不用 `logging.getLogger(__name__)` 直接获取？** 原始 `logging.getLogger()` 返回标准 `Logger`，不自动注入 `trace_id`。虽然 `TraceFilter` 在 root logger 层面会为所有 LogRecord 注入 `trace_id`，但 `KnowraLogger` 通过 `LoggerAdapter.process()` 在更早的阶段（`extra` 合并）完成注入，双重保障更可靠。同时 `KnowraLogger` 的 `extra` 参数对象风格更符合结构化日志习惯。

### 2. 日志级别选择

```
DEBUG   — 调试信息（函数入口/出口、trace_id 生成、健康检查请求）
INFO    — 正常业务操作成功（文件写入完成、DB commit 成功、engine 创建、init_db）
WARNING — 可恢复异常/业务校验不通过（不支持的文件类型、空文件、用户不存在、文件超大）
ERROR   — 不可恢复错误（存储写入失败、DB commit 失败/rollback、元数据保存失败）
```

REFERENCE：Python 标准 logging 级别定义 + 业界惯例（WARNING 用于客户端可修复的问题，ERROR 用于服务端需人工介入的问题）。

### 3. 日志不修改异常抛出逻辑

这是一个重要决策：日志仅追加在异常抛出**之前**，不替代、不包装、不修改异常本身。现有异常类型和 HTTP 状态码完全保持不变。这确保变更的风险最小——纯粹是观测性增强，不改变控制流。

### 4. database_url 脱敏

`db/session.py` 在记录 engine 创建日志时需要输出 `database_url`，但原始 URL 包含密码。需对 URL 做密码脱敏处理：将 `://user:password@host` 替换为 `://user:***@host`。

### 5. 文件上传日志的字段选择

`UploadService.create_upload()` 是当前最复杂的业务方法，涉及文件写入、校验、数据库操作和异常清理。日志字段选择原则：
- 包含可定位资源的标识（`upload_id`、`storage_key`）
- 包含可判断结果的指标（`byte_size`、`checksum_sha256`）
- 包含异常的上下文（`content_type`、`error`）
- 不包含文件内容本身或敏感信息

## Risks / Trade-offs

- **[性能] 日志调用增加 I/O 开销** → 日志写入是异步的（通过 `RotatingFileHandler`），且日志调用本身是轻量操作（~μs 级）。DEBUG 级别日志在生产环境（`debug=false`）不会输出到 console。风险极低。
- **[噪音] DEBUG 级别日志可能过多** → 仅 `middleware/trace.py` 和 `routes/health.py` 使用 DEBUG 级别，其余模块使用 INFO 及以上。健康检查调用频繁时可考虑后续降为不记录或采样，当前先接入观察。
- **[测试] 日志输出可能干扰测试用例** → pytest 默认会捕获 logging 输出。现有测试不验证日志内容，新增测试需显式配置 `caplog` fixture。不影响已有测试。
- **[兼容] 不涉及 API 变更、schema 变更、配置变更** → 回滚仅需 revert git commit，零迁移成本。
