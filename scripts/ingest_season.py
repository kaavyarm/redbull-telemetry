"""Backfill a full F1 season into Postgres: enumerate every round that's
already happened via FastF1's event schedule, ingest each one with tiered
telemetry retention (Red Bull + that session's rivals get full car/
position telemetry; everyone else still gets laps/results/stints), and
skip sessions already marked 'done' in ingestion_runs so a long backfill
can be safely interrupted and resumed.

Usage:
    python scripts/ingest_season.py 2026
    python scripts/ingest_season.py 2026 --rounds 1 2 3
    python scripts/ingest_season.py 2026 --dry-run

Requires DATABASE_URL and SUPABASE_OWNER_USER_ID -- see .env.example.
Reuses ingest.orchestration.ingest_weekend() for the actual pull/write, per
round -- no subprocess spawning, no duplicated FastF1/DB logic.

Set INGEST_SESSION_DELAY_S to override the pacing delay (seconds) between
successive session loads within a round (default 3.0) -- first-time pulls
get no benefit from FastF1's on-disk cache, unlike a re-run of the same
session.

Set SENTRY_DSN to report exceptions to Sentry; unset, this runs with
structured logging only (see observability/).
"""
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import fastf1
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import get_connection  # noqa: E402
from ingest.orchestration import CACHE_DIR, has_session, ingest_weekend  # noqa: E402
from ingest.sources import slugify  # noqa: E402
from ingest.tiering import DEFAULT_RIVAL_TIER_SIZE  # noqa: E402
from observability.logging_config import get_logger, log_fields  # noqa: E402
from observability.sentry import init_sentry  # noqa: E402

log = get_logger("ingest_season")

SESSION_LOAD_DELAY_S = float(os.environ.get("INGEST_SESSION_DELAY_S", "3.0"))


def _elapsed_rounds(year: int, rounds_filter) -> list[int]:
    fastf1.Cache.enable_cache(str(CACHE_DIR))
    schedule = fastf1.get_event_schedule(year)
    # EventDate comes back as tz-naive datetime64[ns] (confirmed against a
    # real fastf1.get_event_schedule() call) -- comparing against a
    # tz-aware timestamp raises, so this stays naive too.
    elapsed = schedule[schedule["EventDate"] < datetime.now()]
    # RoundNumber 0 is pre-season testing, not a real event with sessions.
    round_numbers = sorted(int(r) for r in elapsed["RoundNumber"].tolist() if r > 0)
    if rounds_filter:
        wanted = set(rounds_filter)
        round_numbers = [r for r in round_numbers if r in wanted]
    return round_numbers


def _session_status(cur, year: int, round_number: int, session_type: str) -> str | None:
    cur.execute(
        "select status from public.ingestion_runs where season=%s and round_number=%s and session_type=%s",
        (year, round_number, session_type),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _record_status(cur, year, round_number, session_type, status, tier_summary=None, error=None) -> None:
    cur.execute(
        """
        insert into public.ingestion_runs
          (season, round_number, session_type, status, tier_summary, error, attempted_at)
        values (%s, %s, %s, %s, %s, %s, now())
        on conflict (season, round_number, session_type) do update set
          status = excluded.status, tier_summary = excluded.tier_summary, error = excluded.error,
          attempted_at = excluded.attempted_at
        """,
        (year, round_number, session_type, status,
         psycopg2.extras.Json(tier_summary) if tier_summary is not None else None, error),
    )


def _pending_sessions(event, year: int, round_number: int, conn) -> list[tuple[str, str]]:
    """Which of this round's FastF1 session slots (1-5) still need
    ingesting, as (fastf1_session_id, session_type) pairs.
    slugify(event.get_session_name(i)) gives the same session_type
    transform_session() would assign, without a full session.load()."""
    pending = []
    with conn.cursor() as cur:
        for i in range(1, 6):
            if not has_session(event, i):
                continue
            session_type = slugify(event.get_session_name(i))
            if _session_status(cur, year, round_number, session_type) == "done":
                continue
            pending.append((str(i), session_type))
    return pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("--rounds", nargs="*", type=int, default=None, help="restrict to these round numbers")
    parser.add_argument("--rival-tier-size", type=int, default=DEFAULT_RIVAL_TIER_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="enumerate + tier-plan only, no writes")
    args = parser.parse_args()

    sentry_active = init_sentry("ingest")
    log_fields(log, logging.INFO, "starting ingest_season", year=args.year, dry_run=args.dry_run,
               sentry=sentry_active)

    owner_user_id = os.environ.get("SUPABASE_OWNER_USER_ID")
    if not owner_user_id and not args.dry_run:
        sys.exit("SUPABASE_OWNER_USER_ID is not set -- see .env.example")

    round_numbers = _elapsed_rounds(args.year, args.rounds)
    log_fields(log, logging.INFO, "elapsed rounds", year=args.year, rounds=round_numbers)

    conn = get_connection()
    try:
        for round_number in round_numbers:
            event = fastf1.get_event(args.year, round_number)
            pending = _pending_sessions(event, args.year, round_number, conn)
            if not pending:
                log_fields(log, logging.INFO, "round already fully ingested, skipping", round=round_number)
                continue

            if args.dry_run:
                log_fields(log, logging.INFO, "dry-run: would ingest", round=round_number,
                           sessions=[st for _, st in pending])
                continue

            session_ids = [sid for sid, _ in pending]
            with conn.cursor() as cur:
                for _, session_type in pending:
                    _record_status(cur, args.year, round_number, session_type, "running")
            conn.commit()

            try:
                results = ingest_weekend(
                    args.year, round_number, session_ids=session_ids, conn=conn, owner_user_id=owner_user_id,
                    apply_tiering=True, rival_tier_size=args.rival_tier_size,
                    session_load_delay_s=SESSION_LOAD_DELAY_S,
                )
            except Exception as exc:
                with conn.cursor() as cur:
                    for _, session_type in pending:
                        _record_status(cur, args.year, round_number, session_type, "failed", error=str(exc))
                conn.commit()
                log.exception("round %d failed, will retry on next run", round_number)
                continue

            with conn.cursor() as cur:
                for session_type, info in results.items():
                    _record_status(cur, args.year, round_number, session_type, "done",
                                    tier_summary={"telemetry_driver_count": info["telemetry_driver_count"]})
            conn.commit()
            log_fields(log, logging.INFO, "round ingested", round=round_number, sessions=list(results.keys()))
    finally:
        conn.close()

    log_fields(log, logging.INFO, "ingest_season done", year=args.year)


if __name__ == "__main__":
    main()
