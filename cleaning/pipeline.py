"""Orchestrates cleaning for an already-ingested session: read it back from
Postgres (the source of truth post-ingestion, not the FastF1 fixture/live
pull again), run the detectors, write the findings."""
import pandas as pd

from cleaning.db import write_cleaning_results
from cleaning.detectors import build_lap_exclusions, build_session_quality_flags, derive_caution_periods


def _read(conn, sql: str, session_id: int) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, (session_id,))
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


def load_session_data_from_db(conn, session_id: int) -> dict:
    laps = _read(conn, """
        select driver_id, lap_number, lap_start_time, lap_time, sector1_time, sector2_time,
               sector3_time, deleted, deleted_reason, pit_in_time, pit_out_time, is_accurate
        from public.laps where session_id = %s
    """, session_id)
    track_status_events = _read(conn, """
        select occurred_at, status_code, message from public.track_status_events where session_id = %s
    """, session_id)
    session_status_events = _read(conn, """
        select occurred_at, status from public.session_status_events where session_id = %s
    """, session_id)
    session_results = _read(conn, """
        select driver_id from public.session_results where session_id = %s
    """, session_id)
    car_telemetry = _read(conn, """
        select driver_id, rpm, speed, n_gear, throttle, brake, drs
        from public.car_telemetry_samples where session_id = %s
    """, session_id)
    position_telemetry = _read(conn, """
        select driver_id, x, y, z from public.position_telemetry_samples where session_id = %s
    """, session_id)
    return {
        "laps": laps,
        "track_status_events": track_status_events,
        "session_status_events": session_status_events,
        "session_results": session_results,
        "car_telemetry": car_telemetry,
        "position_telemetry": position_telemetry,
    }


def run_cleaning_for_session(conn, session_id: int) -> dict:
    data = load_session_data_from_db(conn, session_id)

    caution_periods = derive_caution_periods(data["track_status_events"])
    lap_exclusions = build_lap_exclusions(data["laps"], caution_periods)
    quality_flags = build_session_quality_flags(
        data["session_status_events"], data["session_results"],
        data["car_telemetry"], data["position_telemetry"],
    )

    write_cleaning_results(conn, session_id, caution_periods, lap_exclusions, quality_flags)

    return {
        "caution_periods": len(caution_periods),
        "lap_exclusions": len(lap_exclusions),
        "quality_flags": len(quality_flags),
    }
