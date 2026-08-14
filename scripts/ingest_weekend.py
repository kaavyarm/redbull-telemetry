"""Pull one FastF1 race weekend live and ingest it into Postgres.

Usage:
    python scripts/ingest_weekend.py 2026 11
    python scripts/ingest_weekend.py 2026 11 --sessions 4 5   # Q + R only

Requires DATABASE_URL (a direct/session-mode Postgres connection string to
the Supabase project, service_role-equivalent access) and
SUPABASE_OWNER_USER_ID (the single dashboard user's auth.users.id) -- see
.env.example. Safe to re-run: see ingest/db.py's docstring for the
idempotency strategy.

Set SENTRY_DSN to report exceptions to Sentry; unset, this runs with
structured logging only (see observability/).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import fastf1

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import get_connection, write_session  # noqa: E402
from ingest.sources import load_session_source_from_fastf1  # noqa: E402
from ingest.transform import transform_session  # noqa: E402
from observability.logging_config import get_logger, log_fields  # noqa: E402
from observability.sentry import init_sentry  # noqa: E402
from observability.timing import timed_block  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".fastf1_cache"

log = get_logger("ingest_weekend")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("round", type=int)
    parser.add_argument("--sessions", nargs="*", default=None, help="FastF1 session identifiers, e.g. 4 5 or Q R")
    args = parser.parse_args()

    sentry_active = init_sentry("ingest")
    log_fields(log, logging.INFO, "starting ingest_weekend", year=args.year, round=args.round,
               sentry=sentry_active)

    owner_user_id = os.environ.get("SUPABASE_OWNER_USER_ID")
    if not owner_user_id:
        sys.exit("SUPABASE_OWNER_USER_ID is not set -- see .env.example")

    fastf1.Cache.enable_cache(str(CACHE_DIR))

    event = fastf1.get_event(args.year, args.round)
    session_ids = args.sessions
    if session_ids is None:
        session_ids = [str(i) for i in range(1, 6) if _has_session(event, i)]

    conn = get_connection()
    try:
        for sid in session_ids:
            session = fastf1.get_session(args.year, args.round, sid)
            session.load()
            log_fields(log, logging.INFO, "transforming + writing session",
                       event=event["EventName"], session=sid, session_name=session.name)
            source = load_session_source_from_fastf1(session)
            transformed = transform_session(source)

            with timed_block(log, "wrote session", session=sid, laps=len(transformed.laps),
                              car_telemetry=len(transformed.car_telemetry_samples),
                              position_telemetry=len(transformed.position_telemetry_samples)):
                db_session_id = write_session(conn, transformed, owner_user_id)

            log_fields(log, logging.INFO, "session written", sessions_id=db_session_id)
    except Exception:
        log.exception("ingest_weekend failed")
        raise
    finally:
        conn.close()

    log_fields(log, logging.INFO, "ingest_weekend done", year=args.year, round=args.round)


def _has_session(event, i: int) -> bool:
    try:
        name = event.get_session_name(i)
    except Exception:
        return False
    return bool(name) and not isinstance(name, float)


if __name__ == "__main__":
    main()
