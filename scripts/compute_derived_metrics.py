"""Run the derived-metrics analytics service for every already-ingested+
cleaned session of a race weekend.

Usage:
    python scripts/compute_derived_metrics.py 2026 11

Requires DATABASE_URL (see .env.example) and that scripts/ingest_weekend.py
+ scripts/clean_weekend.py have already run for this weekend -- this reads
sessions/laps/telemetry back from Postgres, it doesn't pull from FastF1.

Set SENTRY_DSN to report exceptions to Sentry; unset, this runs with
structured logging only (see observability/).
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import get_connection  # noqa: E402
from analytics.service import run_derived_metrics_for_session  # noqa: E402
from observability.logging_config import get_logger, log_fields  # noqa: E402
from observability.sentry import init_sentry  # noqa: E402
from observability.timing import timed_block  # noqa: E402

log = get_logger("compute_derived_metrics")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("round", type=int)
    args = parser.parse_args()

    sentry_active = init_sentry("analytics")
    log_fields(log, logging.INFO, "starting compute_derived_metrics", year=args.year, round=args.round,
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
                      "scripts/ingest_weekend.py and scripts/clean_weekend.py first.")

        for session_id, session_type in sessions:
            with timed_block(log, "computed derived metrics", session_id=session_id, session_type=session_type):
                counts = run_derived_metrics_for_session(conn, session_id)
            log_fields(log, logging.INFO, "derived metric counts", session_id=session_id, **counts)
    except Exception:
        log.exception("compute_derived_metrics failed")
        raise
    finally:
        conn.close()

    log_fields(log, logging.INFO, "compute_derived_metrics done", year=args.year, round=args.round)


if __name__ == "__main__":
    main()
