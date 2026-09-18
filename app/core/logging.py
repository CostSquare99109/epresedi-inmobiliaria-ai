"""Structured logging setup + request_id context."""
from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

from telegram.error import NetworkError, TimedOut

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_REDACT_KEYS = {"api_key", "token", "password", "secret", "authorization", "nvidia_api_key"}


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        low = msg.lower()
        if any(k in low for k in _REDACT_KEYS):
            record.msg = "[redacted log line: potential secret]"
            record.args = None
        return True


class NetworkErrorFilter(logging.Filter):
    """Colapsa tracebacks de NetworkError/TimedOut del polling de Telegram
    (reconexiones normales) a una sola linea de warning legible."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc_type, exc_val = record.exc_info[0], record.exc_info[1]
            if exc_type and issubclass(exc_type, (NetworkError, TimedOut)):
                record.msg = f"telegram_polling_reconnect: {exc_val}"
                record.args = None
                record.exc_info = None
                record.exc_text = None
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.addFilter(NetworkErrorFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
