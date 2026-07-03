## Why

当前后端自研日志模块（`backend/app/core/logging.py`，243 行）在项目早期阶段运行良好，但随着模块增多，每次输出结构化日志都需要手动传递 `extra={"key": val}`，无法像 `logger.bind(user_id=...)` 那样让上下文自动沿调用链传播。此外，自定义的 `ConsoleFormatter`、`JsonFormatter` 以及 key=value 格式化逻辑需要自行维护，而 `structlog` 作为 Python 结构化日志的事实标准，已将这些能力内置并持续演进。本次迁移用 ~50 行 `structlog` 配置替换 243 行自研代码，净减少约 150 行维护负担，同时获得上下文绑定等开发体验提升。

## What Changes

- **依赖变更**：新增 `structlog` 依赖到 `pyproject.toml`
- **替换日志核心**：重写 `backend/app/core/logging.py`，用 `structlog` 的 processor 管道替代自定义 `ConsoleFormatter`、`JsonFormatter` 和 `KnowraLogger`，删除所有自定义 formatter 和 adapter 代码
- **保留不变**：`backend/app/core/trace_context.py`（contextvars 追踪上下文）和 `TraceFilter`（第三方库 trace_id 注入）完全保留，不做修改
- **调用点更新**：约 20 处 `get_logger(__name__)` 调用点改为 `structlog.get_logger(__name__)`，`extra={}` 改为 `structlog` 原生关键字参数
- **配置模块适配**：`Settings` 中日志相关配置项保持不变，仍通过环境变量控制
- **开发治理规则更新**：AGENTS.md 中禁止使用 `structlog` 的规则需要同步修改，改为允许/推荐使用 `structlog`
- **AGENTS.md 规则更新**（**BREAKING**）：原规则"禁止使用第三方日志库（如 loguru、structlog 等）"将修改为"后端 MUST 使用 structlog 输出日志"

## Capabilities

### New Capabilities

（无新增能力——本次为日志实现层替换，不引入新的产品功能。）

### Modified Capabilities

- `backend-structured-logging`：日志系统的底层实现从自研 LoggerAdapter + 自定义 Formatter 替换为 structlog processor 管道。对外接口 `get_logger()` 的行为语义保持不变（自动注入 trace_id、支持结构化 extra 字段、支持 console/json 双模式），但底层实现变更为 structlog。spec 中涉及 `KnowraLogger`、`ConsoleFormatter`、`JsonFormatter` 类名的描述需更新为实现无关的表述。

## Impact

- **代码**：`backend/app/core/logging.py`（重写）、`backend/app/core/config.py`（微调）、约 10 个业务模块的约 20 处 logger 调用点（适配新 API）
- **依赖**：`pyproject.toml` 新增 `structlog` 依赖
- **测试**：`tests/core/test_logging.py` 需要适配新的 formatter 行为
- **文档**：`AGENTS.md` 中的日志使用规则需要更新
- **API 契约**：无变更——`get_logger()` 签名和行为保持向后兼容
- **配置**：无变更——`Settings` 中日志配置项保持不变
- **数据库**：无 schema 变更
