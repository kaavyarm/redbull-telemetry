"""The real logic behind pulling one FastF1 race weekend and writing it to
Postgres -- extracted from scripts/ingest_weekend.py so
scripts/ingest_season.py can call it in a loop without duplicating the
FastF1/transform/write pipeline or spawning subprocesses. That script
remains a thin CLI wrapper around ingest_weekend() below; apply_tiering=False
(its default, and every call scripts/ingest_weekend.py makes) reproduces
the original unfiltered single-weekend behavior exactly.
"""
import logging
from pathlib import Path

import fastf1

from ingest.db import get_connection, write_session
from ingest.rate_limit import pace, with_retry
from ingest.sources import load_session_source_from_fastf1
from ingest.tiering import DEFAULT_RIVAL_TIER_SIZE, determine_telemetry_tier
from ingest.transform import transform_session
from observability.logging_config import get_logger, log_fields
from observability.timing import timed_block

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".fastf1_cache"

log = get_logger("ingest.orchestration")


def has_session(event, i: int) -> bool:
    """Public (not underscore-prefixed) because scripts/ingest_season.py
    also needs it, to enumerate a round's session slots before deciding
    which ones are already done -- without a full session.load()."""
    try:
        name = event.get_session_name(i)
    except Exception:
        return False
    return bool(name) and not isinstance(name, float)


def ingest_weekend(year: int, round_number: int, session_ids=None, conn=None, owner_user_id=None,
                    apply_tiering: bool = False, rival_tier_size: int = DEFAULT_RIVAL_TIER_SIZE,
                    session_load_delay_s: float = 0.0) -> dict:
    """Pulls + writes every session of one weekend. apply_tiering=False (the
    default, matching ingest_weekend.py's original single-weekend CLI
    behavior) writes full car/position telemetry for every driver.
    apply_tiering=True restricts it to Red Bull + that session's rivals
    (see ingest/tiering.py), computed per-session right after
    transform_session() produces session_results -- tiering needs that
    data, so it can't be decided by the caller ahead of time.
    Returns {session_type: {"session_id": db_session_id, "telemetry_driver_count": int|None}}
    -- telemetry_driver_count is None when apply_tiering=False (unfiltered).

    Manages its own connection (opened and closed here) when conn isn't
    passed in, so a single call is self-contained for one-off use; a
    season-level caller can pass a shared connection across many rounds
    instead of opening one per round.
    """
    if not owner_user_id:
        raise ValueError("owner_user_id is required -- see .env.example's SUPABASE_OWNER_USER_ID")

    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()

    fastf1.Cache.enable_cache(str(CACHE_DIR))
    event = fastf1.get_event(year, round_number)
    if session_ids is None:
        session_ids = [str(i) for i in range(1, 6) if has_session(event, i)]

    results = {}
    try:
        for index, sid in enumerate(session_ids):
            if index > 0:
                pace(session_load_delay_s)

            session = fastf1.get_session(year, round_number, sid)
            with_retry(session.load)
            log_fields(log, logging.INFO, "transforming + writing session",
                       event=event["EventName"], session=sid, session_name=session.name)
            source = load_session_source_from_fastf1(session)
            transformed = transform_session(source)

            telemetry_driver_ids = None
            if apply_tiering:
                telemetry_driver_ids = determine_telemetry_tier(
                    transformed.session_results, transformed.laps, transformed.meta.session_type,
                    rival_tier_size,
                )

            with timed_block(log, "wrote session", session=sid, laps=len(transformed.laps),
                              car_telemetry=len(transformed.car_telemetry_samples),
                              position_telemetry=len(transformed.position_telemetry_samples)):
                db_session_id = write_session(conn, transformed, owner_user_id, telemetry_driver_ids)

            results[transformed.meta.session_type] = {
                "session_id": db_session_id,
                "telemetry_driver_count": len(telemetry_driver_ids) if telemetry_driver_ids is not None else None,
            }
    finally:
        if owns_connection:
            conn.close()

    return results
