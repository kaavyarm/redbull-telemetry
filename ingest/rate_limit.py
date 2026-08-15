"""Retry/backoff + pacing for FastF1 session loads. Nothing like this
exists in the single-weekend path (ingest_weekend.py has always been a
one-shot, manually-run command) -- it starts mattering once
scripts/ingest_season.py loops over ~100+ first-time session loads back to
back, where fastf1.Cache's on-disk cache (which only speeds up *repeat*
pulls) provides no help at all.
"""
import logging
import time

log = logging.getLogger("ingest.rate_limit")


def with_retry(fn, *, max_attempts: int = 5, base_delay_s: float = 2.0, backoff_factor: float = 2.0):
    """Calls fn() with no arguments, retrying on any exception up to
    max_attempts times with exponential backoff. Re-raises the last
    exception if every attempt fails. A plain wrapper rather than a
    decorator, since the one call site (ingest/orchestration.py's
    session.load()) already has the call fully formed as a closure."""
    delay = base_delay_s
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception:
            if attempt == max_attempts:
                raise
            log.warning("attempt %d/%d failed, retrying in %.1fs", attempt, max_attempts, delay)
            time.sleep(delay)
            delay *= backoff_factor


def pace(delay_s: float) -> None:
    """Fixed delay between successive session loads within a round --
    separate from with_retry's backoff, which only fires on failure."""
    if delay_s > 0:
        time.sleep(delay_s)
