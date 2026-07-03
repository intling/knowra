## 1. 依赖与准备

- [x] 1.1 在 `backend/pyproject.toml` 中添加 `structlog>=25.0` 依赖，运行 `uv sync` 锁定版本

## 2. 测试先行 (RED)

- [x] 2.1 重写 `tests/core/test_logging.py`：删除针对 `ConsoleFormatter`、`JsonFormatter`、`KnowraLogger` 的测试，替换为验证 structlog processor 管道行为的测试（trace_id 自动注入、console 模式彩色输出、JSON 模式单行 JSON、关键字参数结构化字段、文件轮转）
- [x] 2.2 新增 `test_logger_bind()` 测试：验证 `logger.bind()` 上下文绑定后，后续调用自动携带绑定字段，且不污染其他请求
- [x] 2.3 新增 `test_keyword_args_instead_of_extra()` 测试：验证 `logger.info("msg", key=val)` 关键字参数方式产生的日志包含对应字段
- [x] 2.4 运行 `uv run pytest tests/core/test_logging.py -v`，确认所有测试处于 RED（失败）状态——此时 structlog 尚未集成
- [x] 2.5 暂停，等待用户评审红测试代码并回复"继续"

## 3. 核心日志模块重写 (GREEN)

- [x] 3.1 重写 `backend/app/core/logging.py` 中的 `configure_logging()` 函数：使用 `structlog.configure()` 配置 processor 管道（`add_log_level`、`TimeStamper`、`add_logger_name`、`format_exc_info`），根据 `debug`/`log_format` 选择 `ConsoleRenderer` 或 `JSONRenderer`；保留标准库 `logging` 的 handler 配置（StreamHandler + RotatingFileHandler）和 `TraceFilter`
- [x] 3.2 重写 `get_logger(name)` 工厂函数：内部调用 `structlog.get_logger(name)`，返回 `structlog.BoundLogger`
- [x] 3.3 删除 `KnowraLogger` 类、`ConsoleFormatter` 类、`JsonFormatter` 类、`_build_extra_kv()` 函数、`_iter_extra()` 函数、`_COLORS` / `_RESET` 常量
- [x] 3.4 在 `configure_logging()` 中配置 `structlog.contextvars.merge_contextvars` processor，使其与 `trace_context.py` 协作自动注入 `trace_id`
- [x] 3.5 调整 `backend/app/core/config.py` 中 `_resolve_log_format` model_validator 的位置（当前在 `parse_csv_list` 函数内部，需移到 `Settings` 类中）
- [x] 3.6 运行 `uv run pytest tests/core/test_logging.py -v`，确认所有测试通过（GREEN）

## 4. 调用点迁移

- [x] 4.1 搜索所有 `extra={` 日志调用点，将 `logger.info("msg", extra={"key": val})` 替换为 `logger.info("msg", key=val)`
- [x] 4.2 确认 `from app.core.logging import get_logger` import 在所有调用模块中仍然有效
- [x] 4.3 运行 `uv run ruff check .`，修复任何 import 或语法问题
- [x] 4.4 运行 `uv run pytest` 全量测试，确认无回归

## 5. 文档与规则更新

- [x] 5.1 更新 `openspec/config.yaml` 中的后端日志规则：移除"禁止使用 structlog"的表述，更新为"后端 MUST 通过 `from app.core.logging import get_logger` 获取 structlog `BoundLogger` 实例"
- [x] 5.2 更新 `openspec/config.yaml` 中 `configure_logging()` 的说明，提及基于 structlog processor 管道配置

## 6. 最终验证

- [x] 6.1 运行 `uv run ruff check . && uv run ruff format --check .`，确认代码风格通过
- [x] 6.2 运行 `uv run pytest -v`，确认全量测试通过（181 passed, 1 pre-existing failure unrelated to structlog）
- [x] 6.3 启动后端服务（`uv run uvicorn app.main:app`），确认 console 日志输出格式正确，包含 structlog ConsoleRenderer 彩色输出和 trace_id
