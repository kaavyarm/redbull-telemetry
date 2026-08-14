"""Orchestrates the analytics batch job: read an already-ingested+cleaned
session back from Postgres, compute all four derived-metric types, write
them to derived_metrics. Mirrors cleaning/pipeline.py's shape (read from
the DB, not from fixtures/FastF1 again) and reuses its delete-then-insert
idempotency pattern.
"""
import pandas as pd
import psycopg2.extras

from analytics.anomaly import detect_lap_telemetry_anomalies
from analytics.degradation import compute_stint_degradation
from analytics.optimal_lap import compute_driver_optimal_laps, compute_session_optimal_lap
from analytics.similarity import compute_lap_telemetry_delta


def _seconds(td) -> float:
    return td.total_seconds() if pd.notna(td) else float("nan")


def _read(conn, sql: str, params=()) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


def _load_session_data(conn, session_id: int) -> dict:
    laps = _read(conn, """
        select id, driver_id, lap_number, lap_time, sector1_time, sector2_time, sector3_time, compound
        from public.laps where session_id = %s
    """, (session_id,))

    laps_with_stint = _read(conn, """
        select l.id, l.driver_id, l.lap_number, l.lap_time, l.compound, s.stint_number
        from public.laps l join public.stints s on s.id = l.stint_id
        where l.session_id = %s
    """, (session_id,))

    lap_exclusions = _read(conn, """
        select le.lap_id, le.category from public.lap_exclusions le
        join public.laps l on l.id = le.lap_id
        where l.session_id = %s
    """, (session_id,))

    return {"laps": laps, "laps_with_stint": laps_with_stint, "lap_exclusions": lap_exclusions}


_NUMERIC_TELEMETRY_COLS = ["speed", "throttle", "rpm"]


def _floatify(df: pd.DataFrame) -> pd.DataFrame:
    """psycopg2 returns `numeric` columns as decimal.Decimal, which numpy
    can't vectorize arithmetic against (e.g. dividing a Decimal array by a
    Python float raises TypeError) -- cast to float right after reading."""
    for col in _NUMERIC_TELEMETRY_COLS:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def _telemetry_for_lap(conn, session_id: int, lap_id: int) -> pd.DataFrame:
    return _floatify(_read(conn, """
        select session_time, speed from public.car_telemetry_samples
        where session_id = %s and lap_id = %s
    """, (session_id, lap_id)))


def _all_session_telemetry(conn, session_id: int) -> pd.DataFrame:
    return _floatify(_read(conn, """
        select lap_id, session_time, speed, throttle, rpm, brake
        from public.car_telemetry_samples where session_id = %s
    """, (session_id,)))


def _to_records(session_id: int, driver_id, metric_type: str, subject: dict, value: dict) -> dict:
    return {"session_id": session_id, "driver_id": driver_id, "metric_type": metric_type,
            "subject": subject, "value": value}


def _clean_none(d: dict) -> dict:
    """NaN/None floats survive fine in jsonb as null -- but pandas NaN
    specifically needs converting, json.dumps chokes on bare float('nan')."""
    import math
    out = {}
    for k, v in d.items():
        if isinstance(v, float) and math.isnan(v):
            out[k] = None
        else:
            out[k] = v
    return out


def build_derived_metrics(conn, session_id: int) -> list[dict]:
    data = _load_session_data(conn, session_id)
    laps, laps_with_stint, lap_exclusions = data["laps"], data["laps_with_stint"], data["lap_exclusions"]
    records = []

    # -- optimal lap: per driver + session-wide
    if not laps.empty:
        driver_optimal = compute_driver_optimal_laps(laps, lap_exclusions)
        for _, row in driver_optimal.iterrows():
            value = _clean_none(row.drop("driver_id").to_dict())
            records.append(_to_records(session_id, row["driver_id"], "optimal_lap", {"scope": "driver"}, value))

        session_optimal = compute_session_optimal_lap(laps, lap_exclusions)
        records.append(_to_records(session_id, None, "optimal_lap", {"scope": "session"},
                                    _clean_none(session_optimal)))

    # -- stint degradation
    if not laps_with_stint.empty:
        degradation = compute_stint_degradation(laps_with_stint, lap_exclusions)
        for _, row in degradation.iterrows():
            subject = {"stint_number": int(row["stint_number"])}
            value = _clean_none(row.drop(["driver_id", "stint_number"]).to_dict())
            records.append(_to_records(session_id, row["driver_id"], "stint_degradation", subject, value))

    # -- telemetry delta: each driver's fastest clean lap vs. the session's fastest clean lap
    if not laps.empty:
        excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()
        clean_laps = laps[~laps["id"].isin(excluded_ids)].dropna(subset=["lap_time"])
        if not clean_laps.empty:
            session_best = clean_laps.loc[clean_laps["lap_time"].idxmin()]
            session_best_tel = _telemetry_for_lap(conn, session_id, int(session_best["id"]))

            for driver_id, g in clean_laps.groupby("driver_id"):
                driver_best = g.loc[g["lap_time"].idxmin()]
                if driver_best["id"] == session_best["id"]:
                    continue  # this driver set the session's fastest lap -- nothing to compare against
                driver_best_tel = _telemetry_for_lap(conn, session_id, int(driver_best["id"]))
                delta = compute_lap_telemetry_delta(session_best_tel, driver_best_tel)
                if delta is None:
                    continue

                # Reconstructing distance by integrating speed accumulates
                # real numerical error over a lap and can produce a delta
                # trace that disagrees with the lap's actual time difference
                # by several seconds (see analytics/similarity.py). The
                # lap_time column gives an exact ground truth the trace
                # itself can't provide, so every delta gets checked against
                # it rather than trusted at face value.
                known_total_delta_s = _seconds(driver_best["lap_time"]) - _seconds(session_best["lap_time"])
                reliability_gap_s = abs(delta["final_delta_s"] - known_total_delta_s)
                delta["known_total_delta_s"] = known_total_delta_s
                delta["reliable"] = reliability_gap_s < max(1.5, 0.15 * abs(known_total_delta_s))

                subject = {
                    "lap_a": int(session_best["lap_number"]), "lap_a_driver": session_best["driver_id"],
                    "lap_b": int(driver_best["lap_number"]), "lap_b_driver": driver_id,
                }
                records.append(_to_records(session_id, driver_id, "telemetry_delta", subject,
                                            _clean_none(delta)))

    # -- telemetry-based lap anomalies
    all_telemetry = _all_session_telemetry(conn, session_id)
    if not all_telemetry.empty and not laps.empty:
        anomalies = detect_lap_telemetry_anomalies(laps, all_telemetry, lap_exclusions)
        for _, row in anomalies.iterrows():
            subject = {"lap_number": int(row["lap_number"]), "feature": row["feature"]}
            value = _clean_none(row.drop(["driver_id", "lap_number", "feature"]).to_dict())
            records.append(_to_records(session_id, row["driver_id"], "lap_anomaly", subject, value))

    return records


def write_derived_metrics(conn, session_id: int, records: list[dict]) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.derived_metrics where session_id = %s", (session_id,))
            if not records:
                return
            values = [
                (r["session_id"], r["driver_id"], r["metric_type"],
                 psycopg2.extras.Json(r["subject"]), psycopg2.extras.Json(r["value"]))
                for r in records
            ]
            psycopg2.extras.execute_values(
                cur,
                "insert into public.derived_metrics (session_id, driver_id, metric_type, subject, value) values %s",
                values,
            )


def run_derived_metrics_for_session(conn, session_id: int) -> dict:
    records = build_derived_metrics(conn, session_id)
    write_derived_metrics(conn, session_id, records)
    counts = {}
    for r in records:
        counts[r["metric_type"]] = counts.get(r["metric_type"], 0) + 1
    return counts
