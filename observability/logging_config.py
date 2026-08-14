"""Structured logging for the batch pipeline scripts (ingest/clean/compute
derived metrics). Every log record is one line of key=value pairs (session
id, row counts, duration_ms, ...) instead of free-form print() text, so a
real log aggregator (or just `grep`/`awk` over a redirected log file) can
parse it without guessing at column positions. Kept dependency-free
(stdlib logging + a custom Formatter) rather than pulling in structlog for
a handful of scripts.
"""
import logging
import sys

_CONFIGURED = False


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None) or {}
        parts = [f'{k}={_fmt_value(v)}' for k, v in {**base, **extra}.items()]
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _fmt_value(v) -> str:
    s = str(v)
    return f'"{s}"' if " " in s else s


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_fields(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    """logger.info(...) doesn't accept arbitrary kwargs -- this is the
    `extra={"fields": {...}}` boilerplate in one call so call sites read as
    log_fields(log, logging.INFO, "wrote session", session_id=5, rows=1431)."""
    logger.log(level, msg, extra={"fields": fields})
