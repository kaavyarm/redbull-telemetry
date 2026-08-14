"""Sentry init for the Python batch jobs. A no-op when SENTRY_DSN isn't
set -- this is a personal project's local pipeline, not every environment
running it has (or needs) a Sentry account, so this must never be a hard
dependency the scripts fail without.
"""
import os


def init_sentry(service_name: str) -> bool:
    """Returns True if Sentry was actually initialized, False if skipped
    (no SENTRY_DSN) -- callers use this to log which mode they're in rather
    than silently doing nothing with no signal either way."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    )
    sentry_sdk.set_tag("service", service_name)
    return True
