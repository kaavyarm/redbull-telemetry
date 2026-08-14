"""Run the data-quality cleaning pipeline for every already-ingested
session of a race weekend.

Usage:
    python scripts/clean_weekend.py 2026 11

Requires DATABASE_URL (see .env.example) and that scripts/ingest_weekend.py
has already been run for this weekend -- cleaning reads sessions/laps back
from Postgres, it doesn't pull from FastF1.

Set SENTRY_DSN to report exceptions to Sentry; unset, this runs with
structured logging only (see observability/).
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import get_connection  # noqa: E402
from cleaning.pipeline import run_cleaning_for_session  # noqa: E402
from observability.logging_config import get_logger, log_fields  # noqa: E402
from observability.sentry import init_sentry  # noqa: E402
from observability.timing import timed_block  # noqa: E402

log = get_logger("clean_weekend")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("round", type=int)
    args = parser.parse_args()

    sentry_active = init_sentry("clean")
    log_fields(log, logging.INFO, "starting clean_weekend", year=args.year, round=args.round,
               sentry=sentry_active)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select id, session_type from public.sessions where season = %s and round_number = %s "
                "order by id",
                (args.year, args.round),
            )
            sessions = cur.fetchall()
        if not sessions:
            sys.exit(f"No ingested sessions found for {args.year} round {args.round} -- run "
                      "scripts/ingest_weekend.py first.")

        for session_id, session_type in sessions:
            with timed_block(log, "cleaned session", session_id=session_id, session_type=session_type):
                counts = run_cleaning_for_session(conn, session_id)
            log_fields(log, logging.INFO, "cleaning counts", session_id=session_id, **counts)
    except Exception:
        log.exception("clean_weekend failed")
        raise
    finally:
        conn.close()

    log_fields(log, logging.INFO, "clean_weekend done", year=args.year, round=args.round)


if __name__ == "__main__":
    main()
