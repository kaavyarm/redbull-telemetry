"""Pull one FastF1 race weekend live and ingest it into Postgres.

Usage:
    python scripts/ingest_weekend.py 2026 11
    python scripts/ingest_weekend.py 2026 11 --sessions 4 5   # Q + R only

Requires DATABASE_URL (a direct/session-mode Postgres connection string to
the Supabase project, service_role-equivalent access) and
SUPABASE_OWNER_USER_ID (the single dashboard user's auth.users.id) -- see
.env.example. Safe to re-run: see ingest/db.py's docstring for the
idempotency strategy.

This is a thin wrapper around ingest.orchestration.ingest_weekend(), which
also backs scripts/ingest_season.py -- all the FastF1/transform/write logic
lives there, not here.

Set SENTRY_DSN to report exceptions to Sentry; unset, this runs with
structured logging only (see observability/).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.orchestration import ingest_weekend  # noqa: E402
from observability.logging_config import get_logger, log_fields  # noqa: E402
from observability.sentry import init_sentry  # noqa: E402

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

    try:
        results = ingest_weekend(args.year, args.round, session_ids=args.sessions, owner_user_id=owner_user_id)
    except Exception:
        log.exception("ingest_weekend failed")
        raise

    session_ids = {k: v["session_id"] for k, v in results.items()}
    log_fields(log, logging.INFO, "ingest_weekend done", year=args.year, round=args.round, **session_ids)


if __name__ == "__main__":
    main()
