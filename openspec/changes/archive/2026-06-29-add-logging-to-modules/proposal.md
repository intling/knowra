## Why

后端的结构化日志基础设施（`app/core/logging.py`、`app/core/trace_context.py`、`app/middleware/trace.py`）已在 `backend-structured-logging` spec 中完整交付，但当前仅 `app/main.py` 调用了 `configure_logging()`，其余所有业务模块（API 路由、Service 层、DB 层、中间件）均未接入日志系统。生产环境出现异常时，日志中仅能看到 uvicorn 的 access log，完全缺失业务上下文（如文件上传失败原因、用户查询异常、数据库回滚等），导致问题排查依赖猜测而非可观测数据。本变更填补这一差距，让日志基础设施在全部后端模块中真正生效。

## What Changes

- 为后端 7 个未接入日志的模块引入 `get_logger(__name__)` 并添加关键路径日志
- Service 层：`services/uploads.py`（文件写入/校验/commit/rollback/清理全流程）、`services/users.py`（用户查询及异常）
- API 路由层：`routes/uploads.py`（四种异常分支）、`routes/users.py`（503 异常）、`routes/health.py`（健康检查）
- DB 层：`db/session.py`（engine 创建）、`db/init_db.py`（create_all 操作）
- 中间件层：`middleware/trace.py`（trace_id 生成/传递）
- 前端模块已全面接入日志系统，**无需变更**

## Capabilities

### New Capabilities

- `backend-module-logging`: 为后端所有业务模块补充结构化日志，覆盖 API 路由、Service、DB、中间件层的日志接入

### Modified Capabilities

<!-- 无需求变更——日志基础设施 spec 已完整，本变更在现有 spec 范围内填补实现空白 -->

无

## Impact

- 受影响文件：7 个后端模块（`services/uploads.py`、`services/users.py`、`api/routes/uploads.py`、`api/routes/users.py`、`api/routes/health.py`、`db/session.py`、`db/init_db.py`、`middleware/trace.py`）
- 无 API 契约变更、无数据库 schema 变更、无配置变更
- 每个模块仅增加 `from app.core.logging import get_logger` 导入和 `logger = get_logger(__name__)` 实例化，在关键路径上添加结构化日志调用
- 日志自动携带 `trace_id`，无需额外配置
