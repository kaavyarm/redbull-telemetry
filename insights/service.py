"""Orchestrates the insights batch job: read an already-computed session's
derived_metrics + laps + session_results back from Postgres, assemble the
context rules.py's functions need, evaluate every rule, write results to
insight_findings. Mirrors analytics/service.py's shape (read from the DB,
delete-then-insert idempotency) -- run this after
scripts/compute_derived_metrics.py, since it reads derived_metrics rows as
input rather than recomputing them.
"""
import numpy as np
import pandas as pd
import psycopg2.extras

from insights.aggregation import RED_BULL_TEAM_ID, join_team_ids
from insights.rules import evaluate_all_rules


def _read(conn, sql: str, params=()) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


def _seconds(td) -> float:
    return td.total_seconds() if pd.notna(td) else float("nan")


def _build_context(conn, session_id: int) -> dict:
    session_results = _read(conn, """
        select driver_id, team_id from public.session_results where session_id = %s
    """, (session_id,))
    red_bull_driver_ids = sorted(
        session_results.loc[session_results["team_id"] == RED_BULL_TEAM_ID, "driver_id"].unique().tolist()
    )

    degradation_rows = _read(conn, """
        select driver_id, subject, value from public.derived_metrics
        where session_id = %s and metric_type = 'stint_degradation'
    """, (session_id,))
    if degradation_rows.empty:
        degradation_with_team = pd.DataFrame(columns=["driver_id", "stint_number", "slope_s_per_lap", "confidence", "team_id"])
    else:
        degradation = pd.DataFrame({
            "driver_id": degradation_rows["driver_id"],
            "stint_number": degradation_rows["subject"].apply(lambda s: s.get("stint_number")),
            "slope_s_per_lap": degradation_rows["value"].apply(lambda v: v.get("slope_s_per_lap")),
            "confidence": degradation_rows["value"].apply(lambda v: v.get("confidence")),
        })
        degradation_with_team = join_team_ids(degradation, session_results)

    optimal_rows = _read(conn, """
        select driver_id, subject, value from public.derived_metrics
        where session_id = %s and metric_type = 'optimal_lap'
    """, (session_id,))
    time_left_on_table_by_driver = {}
    if not optimal_rows.empty:
        for _, row in optimal_rows.iterrows():
            if row["subject"].get("scope") != "driver":
                continue
            time_left_on_table_by_driver[row["driver_id"]] = row["value"].get("time_left_on_table_s")

    laps = _read(conn, """
        select l.driver_id, l.lap_number, l.sector1_time, l.sector2_time, l.sector3_time
        from public.laps l
        where l.session_id = %s and l.driver_id = any(%s)
          and l.id not in (select lap_id from public.lap_exclusions where session_id = %s)
    """, (session_id, red_bull_driver_ids, session_id))
    if laps.empty:
        red_bull_sector_laps = pd.DataFrame(columns=["driver_id", "lap_number", "sector1_time_s", "sector2_time_s", "sector3_time_s"])
    else:
        red_bull_sector_laps = pd.DataFrame({
            "driver_id": laps["driver_id"],
            "lap_number": laps["lap_number"],
            "sector1_time_s": laps["sector1_time"].apply(_seconds),
            "sector2_time_s": laps["sector2_time"].apply(_seconds),
            "sector3_time_s": laps["sector3_time"].apply(_seconds),
        })

    stint_laps_rows = _read(conn, """
        select l.driver_id, s.stint_number, l.lap_time
        from public.laps l
        join public.stints s on s.id = l.stint_id
        where l.session_id = %s and l.driver_id = any(%s) and l.lap_time is not null
          and l.id not in (select lap_id from public.lap_exclusions where session_id = %s)
    """, (session_id, red_bull_driver_ids, session_id))
    if stint_laps_rows.empty:
        red_bull_stint_laps = pd.DataFrame(columns=["driver_id", "stint_number", "lap_time_s"])
    else:
        red_bull_stint_laps = pd.DataFrame({
            "driver_id": stint_laps_rows["driver_id"],
            "stint_number": stint_laps_rows["stint_number"],
            "lap_time_s": stint_laps_rows["lap_time"].apply(_seconds),
        })

    red_bull_brake_pct_by_driver = _brake_pct_on_fastest_lap(conn, session_id, red_bull_driver_ids)

    return {
        "session_id": session_id,
        "red_bull_driver_ids": red_bull_driver_ids,
        "degradation_with_team": degradation_with_team,
        "time_left_on_table_by_driver": time_left_on_table_by_driver,
        "red_bull_sector_laps": red_bull_sector_laps,
        "red_bull_stint_laps": red_bull_stint_laps,
        "red_bull_brake_pct_by_driver": red_bull_brake_pct_by_driver,
    }


def _brake_pct_on_fastest_lap(conn, session_id: int, driver_ids: list[str]) -> dict:
    """Time-weighted (not sample-count-weighted -- telemetry sampling isn't
    uniform, see docs/SCHEMA.md) share of each driver's fastest clean lap
    spent with the brake channel on."""
    if not driver_ids:
        return {}

    fastest = _read(conn, """
        select l.driver_id, l.id as lap_id, l.lap_time
        from public.laps l
        where l.session_id = %s and l.driver_id = any(%s) and l.lap_time is not null
          and l.id not in (select lap_id from public.lap_exclusions where session_id = %s)
    """, (session_id, driver_ids, session_id))
    if fastest.empty:
        return {}
    fastest_idx = fastest.groupby("driver_id")["lap_time"].idxmin()
    fastest_lap_id_by_driver = dict(zip(fastest.loc[fastest_idx, "driver_id"], fastest.loc[fastest_idx, "lap_id"], strict=True))

    lap_ids = list(fastest_lap_id_by_driver.values())
    telemetry = _read(conn, """
        select lap_id, session_time, brake from public.car_telemetry_samples
        where session_id = %s and lap_id = any(%s)
        order by lap_id, session_time
    """, (session_id, lap_ids))

    result = {}
    for driver_id, lap_id in fastest_lap_id_by_driver.items():
        lap_telemetry = telemetry[telemetry["lap_id"] == lap_id]
        if len(lap_telemetry) < 2:
            continue
        t = lap_telemetry["session_time"].apply(_seconds).to_numpy()
        brake = lap_telemetry["brake"].to_numpy()
        dt = np.diff(t)  # gap until the next sample; each sample's brake state applies for that gap
        total_time = dt.sum()
        if total_time <= 0:
            continue
        brake_time = dt[brake[:-1]].sum()
        result[driver_id] = float(100 * brake_time / total_time)
    return result


def build_insight_findings(conn, session_id: int) -> list[dict]:
    context = _build_context(conn, session_id)
    if not context["red_bull_driver_ids"]:
        return []  # nothing to say about Red Bull if Red Bull isn't in this session
    return evaluate_all_rules(context)


def write_insight_findings(conn, session_id: int, records: list[dict]) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.insight_findings where session_id = %s", (session_id,))
            if not records:
                return
            values = [
                (r["session_id"], r["finding_type"], r["severity"], r["subject_driver_id"],
                 r["compared_against_type"], r["compared_against_driver_id"], r["compared_against_team_id"],
                 r["metric_value"], r["threshold_value"], r["unit"], psycopg2.extras.Json(r["subject"]), r["message"])
                for r in records
            ]
            psycopg2.extras.execute_values(
                cur,
                """insert into public.insight_findings
                   (session_id, finding_type, severity, subject_driver_id, compared_against_type,
                    compared_against_driver_id, compared_against_team_id, metric_value, threshold_value,
                    unit, subject, message)
                   values %s""",
                values,
            )


def run_insights_for_session(conn, session_id: int) -> dict:
    records = build_insight_findings(conn, session_id)
    write_insight_findings(conn, session_id, records)
    counts = {}
    for r in records:
        counts[r["finding_type"]] = counts.get(r["finding_type"], 0) + 1
    return counts
