"""Unit tests for the analytics modules (optimal_lap, degradation,
similarity, anomaly) against hand-built fixtures -- these are pure
functions operating on DB-shaped DataFrames (an `id` column standing in for
the real Postgres-assigned lap id), so no database is needed here.

test_service_integration at the bottom of this file is different: it runs
the full read-from-Postgres -> compute -> write-to-derived_metrics pipeline
against a real ingested session, gated on DATABASE_URL like
test_analytics_parity.py.
"""
import os

import numpy as np
import pandas as pd
import pytest

from analytics.anomaly import detect_lap_telemetry_anomalies
from analytics.degradation import compute_stint_degradation
from analytics.optimal_lap import compute_driver_optimal_laps, compute_session_optimal_lap
from analytics.similarity import compute_lap_telemetry_delta


def td(seconds: float) -> pd.Timedelta:
    return pd.Timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# optimal_lap
# ---------------------------------------------------------------------------

def _laps_for_optimal(rows):
    cols = ["id", "driver_id", "lap_number", "sector1_time", "sector2_time", "sector3_time", "lap_time"]
    return pd.DataFrame(rows, columns=cols)


def test_optimal_lap_sums_best_sectors_across_different_laps():
    laps = _laps_for_optimal([
        (1, "ver", 1, td(30.0), td(35.0), td(28.0), td(93.0)),  # best S1, worst S3
        (2, "ver", 2, td(31.0), td(34.0), td(27.0), td(92.0)),  # best S2 and S3
    ])
    out = compute_driver_optimal_laps(laps, pd.DataFrame(columns=["lap_id", "category"]))
    row = out.iloc[0]
    assert row["best_sector1_s"] == pytest.approx(30.0)
    assert row["best_sector2_s"] == pytest.approx(34.0)
    assert row["best_sector3_s"] == pytest.approx(27.0)
    assert row["optimal_lap_s"] == pytest.approx(91.0)
    assert row["actual_best_lap_s"] == pytest.approx(92.0)
    assert row["time_left_on_table_s"] == pytest.approx(1.0)


def test_optimal_lap_excludes_flagged_laps():
    laps = _laps_for_optimal([
        (1, "ver", 1, td(25.0), td(30.0), td(20.0), td(75.0)),   # implausibly fast -- excluded
        (2, "ver", 2, td(30.0), td(34.0), td(27.0), td(91.0)),
    ])
    exclusions = pd.DataFrame([{"lap_id": 1, "category": "timing_anomaly"}])
    out = compute_driver_optimal_laps(laps, exclusions)
    row = out.iloc[0]
    # only lap 2's sectors should be usable
    assert row["best_sector1_s"] == pytest.approx(30.0)
    assert row["actual_best_lap_s"] == pytest.approx(91.0)


def test_optimal_lap_no_clean_laps_returns_none_values():
    laps = _laps_for_optimal([(1, "ver", 1, td(30.0), td(35.0), td(28.0), td(93.0))])
    exclusions = pd.DataFrame([{"lap_id": 1, "category": "steward_deleted"}])
    out = compute_driver_optimal_laps(laps, exclusions)
    row = out.iloc[0]
    assert row["optimal_lap_s"] is None
    assert row["actual_best_lap_s"] is None


def test_session_optimal_lap_uses_best_across_all_drivers():
    laps = _laps_for_optimal([
        (1, "ver", 1, td(30.0), td(35.0), td(28.0), td(93.0)),
        (2, "nor", 1, td(29.5), td(34.5), td(27.5), td(91.5)),
    ])
    out = compute_session_optimal_lap(laps, pd.DataFrame(columns=["lap_id", "category"]))
    assert out["best_sector1_s"] == pytest.approx(29.5)
    assert out["best_sector2_s"] == pytest.approx(34.5)
    assert out["best_sector3_s"] == pytest.approx(27.5)
    assert out["optimal_lap_s"] == pytest.approx(91.5)


# ---------------------------------------------------------------------------
# degradation
# ---------------------------------------------------------------------------

def _laps_for_degradation(rows):
    cols = ["id", "driver_id", "stint_number", "lap_number", "lap_time", "compound"]
    return pd.DataFrame(rows, columns=cols)


def test_degradation_detects_clear_linear_trend():
    """Lap times increasing by exactly 0.5s/lap -- slope should recover
    that exactly, with a strong R^2."""
    rows = [(i, "ver", 1, i, td(90.0 + 0.5 * (i - 1)), "MEDIUM") for i in range(1, 8)]
    laps = _laps_for_degradation(rows)
    out = compute_stint_degradation(laps, pd.DataFrame(columns=["lap_id", "category"]))
    row = out.iloc[0]
    assert row["slope_s_per_lap"] == pytest.approx(0.5, abs=1e-6)
    assert row["r_squared"] == pytest.approx(1.0, abs=1e-6)
    assert row["confidence"] == "high"
    assert row["clean_lap_count"] == 7


def test_degradation_excludes_flagged_laps_from_fit():
    rows = [(i, "ver", 1, i, td(90.0 + 0.5 * (i - 1)), "MEDIUM") for i in range(1, 6)]
    rows.append((99, "ver", 1, 6, td(200.0), "MEDIUM"))  # wild outlier, e.g. a VSC lap
    laps = _laps_for_degradation(rows)
    exclusions = pd.DataFrame([{"lap_id": 99, "category": "caution_period"}])
    out = compute_stint_degradation(laps, exclusions)
    row = out.iloc[0]
    assert row["clean_lap_count"] == 5
    assert row["slope_s_per_lap"] == pytest.approx(0.5, abs=1e-6)


def test_degradation_single_lap_stint_marked_insufficient():
    laps = _laps_for_degradation([(1, "ver", 1, 1, td(91.0), "SOFT")])
    out = compute_stint_degradation(laps, pd.DataFrame(columns=["lap_id", "category"]))
    row = out.iloc[0]
    assert row["confidence"] == "insufficient_data"
    assert row["clean_lap_count"] == 1


def test_degradation_noisy_laps_get_low_confidence():
    rows = [
        (1, "ver", 1, 1, td(90.0), "SOFT"),
        (2, "ver", 1, 2, td(94.0), "SOFT"),
        (3, "ver", 1, 3, td(89.0), "SOFT"),
        (4, "ver", 1, 4, td(93.0), "SOFT"),
        (5, "ver", 1, 5, td(90.5), "SOFT"),
    ]
    laps = _laps_for_degradation(rows)
    out = compute_stint_degradation(laps, pd.DataFrame(columns=["lap_id", "category"]))
    row = out.iloc[0]
    assert row["confidence"] in ("low", "medium")


def test_degradation_empty_input_returns_empty_frame():
    out = compute_stint_degradation(_laps_for_degradation([]), pd.DataFrame(columns=["lap_id", "category"]))
    assert out.empty


# ---------------------------------------------------------------------------
# similarity (telemetry delta trace)
# ---------------------------------------------------------------------------

def _telemetry(times_s, speeds_kmh):
    return pd.DataFrame({
        "session_time": [td(t) for t in times_s],
        "speed": speeds_kmh,
    })


def test_identical_laps_have_zero_delta():
    times = np.arange(0, 20, 0.5)
    speeds = 200 + 50 * np.sin(times / 3)
    tel = _telemetry(times, speeds)
    out = compute_lap_telemetry_delta(tel, tel.copy())
    assert out is not None
    assert out["final_delta_s"] == pytest.approx(0.0, abs=1e-6)
    assert out["mean_abs_delta_s"] == pytest.approx(0.0, abs=1e-6)


def test_slower_lap_shows_positive_final_delta():
    """Lap B covers the same time window but at 10% lower speed throughout
    -- less distance per unit time means B takes longer to reach any given
    distance than A, so B should show up as behind everywhere."""
    times = np.arange(0, 20, 0.5)
    speeds_a = 200 + 30 * np.sin(times / 3)
    tel_a = _telemetry(times, speeds_a)

    speeds_b = speeds_a * 0.9
    tel_b = _telemetry(times, speeds_b)

    out = compute_lap_telemetry_delta(tel_a, tel_b)
    assert out is not None
    assert out["final_delta_s"] > 0
    assert out["max_loss_s"] >= out["final_delta_s"] - 1e-6


def test_insufficient_telemetry_returns_none():
    tel_a = _telemetry([0.0], [200.0])
    tel_b = _telemetry([0.0, 0.5], [200.0, 205.0])
    assert compute_lap_telemetry_delta(tel_a, tel_b) is None


def test_delta_trace_length_matches_requested_points():
    times = np.arange(0, 20, 0.5)
    speeds = 200 + 30 * np.sin(times / 3)
    tel = _telemetry(times, speeds)
    out = compute_lap_telemetry_delta(tel, tel.copy(), n_points=50)
    assert len(out["delta_trace_s"]) == 50
    assert len(out["distance_grid_m"]) == 50


# ---------------------------------------------------------------------------
# anomaly (telemetry-based, per driver baseline)
# ---------------------------------------------------------------------------

def _car_telemetry(rows):
    cols = ["lap_id", "session_time", "speed", "throttle", "rpm", "brake"]
    return pd.DataFrame(rows, columns=cols)


def _normal_lap_telemetry(lap_id, base_speed=250):
    return [
        (lap_id, td(t), base_speed + (t % 3), 80.0, 11000, t % 4 < 1)
        for t in range(20)
    ]


def test_anomaly_flags_lap_with_unusually_low_max_speed():
    """A single extreme outlier pulls its own reference population's mean
    and std toward it -- with too few baseline laps that self-masks the
    outlier's z-score below any reasonable threshold, a real statistical
    effect confirmed while writing this test, not just a synthetic-data
    quirk. 10 baseline laps keeps the outlier from dominating its own
    comparison population."""
    rows = []
    for lap_id in range(1, 11):
        rows += _normal_lap_telemetry(lap_id, base_speed=250)
    rows += [(11, td(t), 100 + (t % 3), 80.0, 11000, t % 4 < 1) for t in range(20)]  # anomalously slow lap
    car_tel = _car_telemetry(rows)

    laps = pd.DataFrame({"id": range(1, 12), "driver_id": "ver", "lap_number": range(1, 12)})
    out = detect_lap_telemetry_anomalies(laps, car_tel, pd.DataFrame(columns=["lap_id", "category"]))

    flagged = out[(out["lap_number"] == 11) & (out["feature"] == "max_speed")]
    assert len(flagged) == 1
    assert flagged.iloc[0]["z_score"] < -2.5


def test_anomaly_excludes_already_flagged_laps():
    """A pit lane lap with low speed shouldn't be re-flagged as an anomaly
    -- the cleaning pipeline already explains it as a pit_lap exclusion."""
    rows = []
    for lap_id in range(1, 6):
        rows += _normal_lap_telemetry(lap_id, base_speed=250)
    rows += [(6, td(t), 100 + (t % 3), 80.0, 11000, t % 4 < 1) for t in range(20)]
    car_tel = _car_telemetry(rows)

    laps = pd.DataFrame({"id": range(1, 7), "driver_id": "ver", "lap_number": range(1, 7)})
    exclusions = pd.DataFrame([{"lap_id": 6, "category": "pit_lap"}])
    out = detect_lap_telemetry_anomalies(laps, car_tel, exclusions)
    assert out[out["lap_number"] == 6].empty


def test_anomaly_requires_minimum_baseline_laps():
    rows = _normal_lap_telemetry(1) + _normal_lap_telemetry(2)
    car_tel = _car_telemetry(rows)
    laps = pd.DataFrame({"id": [1, 2], "driver_id": "ver", "lap_number": [1, 2]})
    out = detect_lap_telemetry_anomalies(laps, car_tel, pd.DataFrame(columns=["lap_id", "category"]),
                                          min_laps_for_baseline=4)
    assert out.empty


def test_anomaly_empty_telemetry_returns_empty_frame():
    laps = pd.DataFrame({"id": [1], "driver_id": ["ver"], "lap_number": [1]})
    out = detect_lap_telemetry_anomalies(laps, _car_telemetry([]), pd.DataFrame(columns=["lap_id", "category"]))
    assert out.empty


# ---------------------------------------------------------------------------
# full-service integration (real ingested session, gated on DATABASE_URL)
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set -- integration test needs a live Postgres")
def test_service_integration_runs_and_writes_derived_metrics():
    import psycopg2

    from analytics.service import run_derived_metrics_for_session

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("select id from public.sessions order by id limit 1")
            row = cur.fetchone()
            if row is None:
                pytest.skip("no ingested sessions in target database")
            session_id = row[0]

        counts = run_derived_metrics_for_session(conn, session_id)
        assert counts["optimal_lap"] > 0
        assert sum(counts.values()) > 0

        with conn.cursor() as cur:
            cur.execute("select metric_type, count(*) from public.derived_metrics where session_id = %s "
                        "group by metric_type", (session_id,))
            db_counts = dict(cur.fetchall())
        assert db_counts.get("optimal_lap", 0) > 0
    finally:
        conn.close()
