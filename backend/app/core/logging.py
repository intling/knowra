import logging
import sys
from datetime import datetime, timezone


# ── third-party loggers that produce excessive noise ──────────────────
_NOISY_LOGGERS: dict[str, int] = {
    "transformers": logging.WARNING,
    "transformers.configuration_utils": logging.WARNING,
    "transformers.modeling_utils": logging.WARNING,
    "transformers.tokenization_utils_base": logging.WARNING,
    "huggingface_hub": logging.WARNING,
    "tokenizers": logging.WARNING,
    "docling": logging.WARNING,
    "docling_core": logging.WARNING,
    "torch": logging.WARNING,
    "torch.distributed": logging.ERROR,
    "PIL": logging.WARNING,
    "PIL.Image": logging.WARNING,
    "urllib3": logging.WARNING,
    "urllib3.connectionpool": logging.WARNING,
    "httpx": logging.WARNING,
    "fsspec": logging.WARNING,
    "filelock": logging.WARNING,
    "asyncio": logging.WARNING,
    "httpcore": logging.WARNING,
    "sentence_transformers": logging.WARNING,
    "accelerate": logging.WARNING,
    "safetensors": logging.WARNING,
    "tqdm": logging.WARNING,
}


def _silence_noisy_libraries() -> None:
    """Push noisy third-party loggers to WARNING (or ERROR) so they only
    surface real problems."""
    for name, level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(level)


# ── formatters ────────────────────────────────────────────────────────

class _ColourFormatter(logging.Formatter):
    """Coloured console output for human-readable development logs."""

    LEVEL_COLOURS = {
        logging.DEBUG: "\033[2;37m",     # grey
        logging.INFO: "\033[0m",          # default
        logging.WARNING: "\033[33m",      # yellow
        logging.ERROR: "\033[31m",        # red
        logging.CRITICAL: "\033[1;31m",   # bold red
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, "")
        time_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        level = record.levelname

        # application loggers get full detail; third-party loggers get a
        # compact single-line format
        if record.name.startswith("app"):
            base = f"{self.DIM}{time_str}{self.RESET} {colour}{level:<5}{self.RESET} {record.name} | {record.getMessage()}"
        else:
            base = f"{self.DIM}{time_str}{self.RESET} {colour}{level:<5}{self.RESET} [{record.name}] {record.getMessage()}"

        if record.exc_info and record.exc_info[1] is not None:
            base += "\n"
            base += self.formatException(record.exc_info)
        return base


class _PlainFormatter(logging.Formatter):
    """Plain-text single-line format for non-TTY / production."""

    def format(self, record: logging.LogRecord) -> str:
        time_str = datetime.now(timezone.utc).isoformat()
        base = f"{time_str} {record.levelname:<5} [{record.name}] {record.getMessage()}"
        if record.exc_info and record.exc_info[1] is not None:
            base += "\n"
            base += self.formatException(record.exc_info)
        return base


# ── public API ────────────────────────────────────────────────────────

def configure_logging(debug: bool = False, log_level: str = "INFO") -> None:
    """Set up logging for the application.

    * Suppresses noisy third-party loggers (transformers, huggingface, etc.)
    * Coloured output in the terminal; plain text when piped
    * Application-level loggers under ``app.*`` use the configured level
    * ``sqlalchemy.engine`` is set to WARNING (no raw SQL dumps)
    * ``uvicorn.access`` is set to WARNING (HTTP access is handled by
      the request middleware)
    """
    # resolve effective level
    if debug:
        level = logging.DEBUG
    else:
        try:
            level = getattr(logging, log_level.upper())
        except AttributeError:
            level = logging.INFO

    _silence_noisy_libraries()

    # application-level logger threshold
    logging.getLogger("app").setLevel(level)

    # suppress SQLAlchemy raw SQL (use echo=False on engine instead)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # suppress uvicorn access log — middleware handles HTTP logging
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # keep uvicorn.error at the configured level for lifecycle events
    logging.getLogger("uvicorn.error").setLevel(level)

    # root handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _ColourFormatter() if sys.stderr.isatty() else _PlainFormatter()
    )

    root = logging.getLogger()
    root.setLevel(level)
    # replace any pre-existing handlers (e.g. from basicConfig)
    root.handlers.clear()
    root.addHandler(handler)
