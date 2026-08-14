import logging
import time

from observability.logging_config import KeyValueFormatter, log_fields
from observability.sentry import init_sentry
from observability.timing import timed_block


def _make_record(msg, fields=None, level=logging.INFO):
    record = logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None,
    )
    if fields is not None:
        record.fields = fields
    return record


def test_key_value_formatter_includes_base_fields():
    formatter = KeyValueFormatter()
    line = formatter.format(_make_record("hello"))
    assert "level=INFO" in line
    assert "logger=test" in line
    assert "msg=hello" in line


def test_key_value_formatter_includes_extra_fields():
    formatter = KeyValueFormatter()
    line = formatter.format(_make_record("wrote session", fields={"session_id": 5, "rows": 1431}))
    assert "session_id=5" in line
    assert "rows=1431" in line


def test_key_value_formatter_quotes_values_with_spaces():
    formatter = KeyValueFormatter()
    line = formatter.format(_make_record("x", fields={"event_name": "Hungarian Grand Prix"}))
    assert 'event_name="Hungarian Grand Prix"' in line


def test_log_fields_attaches_extra(caplog):
    logger = logging.getLogger("test.log_fields")
    with caplog.at_level(logging.INFO, logger="test.log_fields"):
        log_fields(logger, logging.INFO, "did a thing", foo="bar", n=3)
    assert len(caplog.records) == 1
    assert caplog.records[0].fields == {"foo": "bar", "n": 3}


def test_init_sentry_is_a_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry("test-service") is False


def test_init_sentry_initializes_when_dsn_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fakehost/1")
    assert init_sentry("test-service") is True


def test_timed_block_logs_duration(caplog):
    logger = logging.getLogger("test.timing")
    with caplog.at_level(logging.INFO, logger="test.timing"):
        with timed_block(logger, "did some work", extra_field=1):
            time.sleep(0.01)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.fields["extra_field"] == 1
    assert record.fields["duration_ms"] >= 10


def test_timed_block_logs_even_when_the_block_raises(caplog):
    logger = logging.getLogger("test.timing_error")
    with caplog.at_level(logging.INFO, logger="test.timing_error"):
        try:
            with timed_block(logger, "will fail"):
                raise ValueError("boom")
        except ValueError:
            pass
    assert len(caplog.records) == 1
    assert "duration_ms" in caplog.records[0].fields
