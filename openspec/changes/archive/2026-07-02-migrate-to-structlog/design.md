## Context

当前日志系统由 `backend/app/core/logging.py`（243 行）实现，核心组件包括：自定义 `KnowraLogger`（`LoggerAdapter` 子类）、自定义 `ConsoleFormatter` 和 `JsonFormatter`、`TraceFilter`（注入 trace_id）以及 `configure_logging()` 配置函数。该系统依赖 Python 标准库 `logging` 模块，外部零依赖。

整个代码库中约有 10 个模块、20 处调用点使用 `get_logger(__name__)` 获取 logger 实例，通过 `logger.info("msg", extra={"key": val})` 输出结构化日志。

`structlog` 是 Python 生态系统中最广泛采用的结构化日志库，通过 processor 管道模式实现"收集上下文 → 格式化 → 渲染输出"的清晰数据流。其 `structlog.stdlib` 模块完全兼容标准库 `logging`，意味着 SQLAlchemy、uvicorn、alembic 等第三方库的日志无需任何改动即可继续工作。

## Goals / Non-Goals

**Goals:**
- 用 `structlog` 的 processor 管道替代自定义 `ConsoleFormatter`、`JsonFormatter` 和 `KnowraLogger`，净减少 ~150 行维护代码
- 保持对外接口 `get_logger()` 的向后兼容，业务代码改动量最小
- 保持 trace_id 自动注入、console/json 双模式切换、文件滚动落盘三大核心行为不变
- 保留 `trace_context.py` 和 `TraceFilter` 不变，确保第三方库日志继续携带 trace_id

**Non-Goals:**
- 不改变前端日志系统（本次仅涉及后端）
- 不引入 `Loguru`（与 stdlib logging 生态集成不自然）
- 不改变日志配置项（`Settings` 中日志属性名和默认值保持不变）
- 不改变 `TraceMiddleware` 的行为
- 不在此次变更中引入日志采样、异步日志等高级特性

## Decisions

### 决策 1：选择 structlog 而非 Loguru

**选择**：`structlog`

**理由**：
- `structlog.stdlib` 模块提供与标准库 `logging` 的零摩擦桥接——它创建的 logger 底层就是 `logging.Logger`，所有已有的 handler、filter、formatter 配置继续生效
- Loguru 使用完全独立的 API（`logger.info()` 不走标准库），需要 intercept handler 来桥接 SQLAlchemy、uvicorn 等第三方库日志。项目已经为这些集成做了不少工作（TraceFilter + lifespan 接管），切到 Loguru 意味着全部重做
- `structlog` 的 processor 管道模型天然适合我们的需求——trace_id 注入、上下文渲染、格式切换都可以作为独立 processor 组合

### 决策 2：保留 TraceFilter 不动

**选择**：`TraceFilter`（`logging.Filter` 子类）完全保留

**理由**：`TraceFilter` 工作在 root logger 级别，在 `LogRecord` 被创建后、被 handler 处理前注入 `trace_id`。这个机制对 structlog 也是透明的——structlog 的 `StructlogFormatter`（或我们配置的 renderer）从 `LogRecord.trace_id` 属性上读取值即可。TraceFilter 的价值在于让 SQLAlchemy、uvicorn 等不走 structlog 的第三方库日志也能获得 trace_id，这一需求不变。

### 决策 3：structlog processor 管道架构

**选择**：使用以下 processor 管道：

```
                                请求进入
                                   │
                    ┌──────────────▼──────────────┐
                    │ structlog.contextvars.       │
                    │ bind_contextvars(trace_id=…) │
                    │ (从 trace_context 注入)       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ structlog.processors.        │
                    │ add_log_level               │
                    │ TimeStamper(fmt="iso")       │
                    │ add_logger_name              │
                    │ format_exc_info              │
                    │ StackInfoRenderer()          │
                    │ UnicodeDecoder()             │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ structlog.dev.ConsoleRenderer│  ← debug=true
                    │ 或                           │
                    │ structlog.processors.JSONRenderer│ ← debug=false
                    └──────────────────────────────┘
```

- `trace_id` 在 `TraceMiddleware` 设置 `contextvars` 后，通过 `structlog.contextvars.bind_contextvars()` 自动注入到每条 structlog 日志
- 对于非 structlog 路径（SQLAlchemy、uvicorn），`TraceFilter` 仍然工作——它设置 `record.trace_id`，由最后的 renderer 读取
- `ConsoleRenderer` 提供开发友好的彩色输出（比当前手工 ANSI 代码更健壮）
- `JSONRenderer` 确保生产环境每行一个 JSON 对象

### 决策 4：get_logger() 保持向后兼容

**选择**：保留 `get_logger(name: str)` 函数签名，内部改为调用 `structlog.get_logger(name)`

**理由**：
- 调用点适配代码最少（约 20 处基本只需改 `extra={}` → 关键字参数）
- 如果将来需要切换底层实现，只需改这一个工厂函数
- `structlog.get_logger()` 返回的 `BoundLogger` 支持 `debug/info/warning/error/exception` 等标准方法，与现有代码兼容

### 决策 5：关键字参数替代 extra={}

**选择**：`logger.info("msg", file_name="x", size=2048)` 替代 `logger.info("msg", extra={"file_name": "x", "byte_size": 2048})`

**理由**：
- structlog 原生支持关键字参数作为结构化字段——不再需要 `extra` 字典包装
- 更简洁、更 Pythonic
- structlog 的 processor 管道自动将这些关键字参数合并到事件字典中

## 架构对比

```
BEFORE (自研)                          AFTER (structlog)
─────────────────────────             ────────────────────────
KnowraLogger(LoggerAdapter)     →     structlog.get_logger()
  .process() 注入 trace_id            + contextvars.bind_contextvars()

ConsoleFormatter                →     structlog.dev.ConsoleRenderer
  - 手写 ANSI 颜色码                  - 内置颜色支持
  - 手写 key=value 格式化             - 自动格式化

JsonFormatter                   →     structlog.processors.JSONRenderer
  - 手写 JSON 序列化                  - 内置 JSON 序列化
  - default=str 兜底                  - 可靠的类型处理

configure_logging()             →     structlog.configure() + configure_logging()
  - 手写 handler 配置                 - processor 链配置
                                      - handler 配置保留（文件滚动）

TraceFilter           保留不变  →     TraceFilter 保留不变
trace_context.py      保留不变  →     trace_context.py 保留不变
```

## Risks / Trade-offs

- **[R1] structlog 作为新依赖引入供应链风险** → 缓解：structlog 是 PyPI 上每周数百万下载量的成熟项目（v25+），由 Hynek Schlawack 维护，依赖链极短（无外部依赖或仅 `colorama`），社区活跃度极高
- **[R2] 调用点迁移可能遗漏** → 缓解：全局搜索 `from app.core.logging import get_logger` 可精确找到所有调用点；ruff lint 会捕获未使用的 import
- **[R3] 测试需要适配** → 缓解：`test_logging.py` 中的 formatter 测试需要重点调整，但核心行为断言（trace_id 注入、JSON 格式、文件轮转）保持可验证
- **[R4] structlog 版本锁定** → 缓解：在 pyproject.toml 中指定 `structlog>=25.0`，uv.lock 锁定确切版本

## Open Questions

（无——技术方案已充分明确，在 explore 阶段已讨论 structlog vs Loguru 的取舍。）
