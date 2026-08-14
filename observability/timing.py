"""Timing helpers for auth/DB calls in the batch pipeline. There's no RPC
layer in this schema (see supabase/schema.sql's header for why), so the
"query timing" concern maps to timing DB writes/reads directly.

`timed_block` is a context manager, not a decorator, because every call
site already has a natural "here's the DB round-trip" boundary (a
`write_session(...)` call, a `cur.execute(...)`) and wrapping just that
line is more honest than timing an entire function that also does
CPU-bound transform work.
"""
import logging
import time
from contextlib import contextmanager

from observability.logging_config import log_fields


@contextmanager
def timed_block(logger, label: str, level: int = logging.INFO, **fields):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_fields(logger, level, label, duration_ms=duration_ms, **fields)
