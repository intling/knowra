import ast
from pathlib import Path

LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def test_app_logger_calls_use_structured_keyword_fields() -> None:
    violations: list[str] = []
    for path in sorted(Path("app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        violations.extend(_collect_logging_style_violations(source, filename=str(path)))

    assert violations == []


def test_logging_style_check_rejects_message_interpolation_variants() -> None:
    source = """
from app.core.logging import get_logger

logger = get_logger(__name__)
logger.info("ok", file_name="notes.pdf")
logger.info("bad %s", "notes.pdf")
logger.info(f"bad {'notes.pdf'}")
logger.info("bad {}".format("notes.pdf"))
logger.info("bad " + "notes.pdf")
logger.info("bad", extra={"file_name": "notes.pdf"})
"""

    violations = _collect_logging_style_violations(source, filename="sample.py")

    assert violations == [
        "sample.py:6 uses positional log args",
        "sample.py:7 uses f-string log event",
        "sample.py:8 uses str.format log event",
        "sample.py:9 uses string concatenation log event",
        "sample.py:10 uses extra= instead of keyword fields",
    ]


def _collect_logging_style_violations(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_logger_call(node):
            continue

        if len(node.args) > 1:
            violations.append(f"{filename}:{node.lineno} uses positional log args")
        if node.args and isinstance(node.args[0], ast.JoinedStr):
            violations.append(f"{filename}:{node.lineno} uses f-string log event")
        if node.args and _is_str_format_call(node.args[0]):
            violations.append(f"{filename}:{node.lineno} uses str.format log event")
        if (
            node.args
            and isinstance(node.args[0], ast.BinOp)
            and isinstance(node.args[0].op, ast.Add)
        ):
            violations.append(f"{filename}:{node.lineno} uses string concatenation log event")
        if any(keyword.arg == "extra" for keyword in node.keywords):
            violations.append(f"{filename}:{node.lineno} uses extra= instead of keyword fields")
    return violations


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in LOGGER_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id == "logger"
    )


def _is_str_format_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )
