"""Unit tests for cleaning/detectors.py.

Most cases here are deliberately hand-built malformed fixtures (a lap with
an impossible time, sector times that don't sum, telemetry with a dead
channel) rather than the pulled fixtures under tests/fixtures/ -- real
data mostly doesn't contain these problems, so the only way to prove a
detector actually catches them is to construct them by hand. A couple of
tests do use real fixtures (session_status timelines with genuine
'Aborted' events, real track_status sequences) to pin down behavior
documented in the module's docstrings.
"""
from pathlib import Path

import pandas as pd

from cleaning.detectors import (
    build_lap_exclusions,
    build_session_quality_flags,
    derive_caution_periods,
    detect_caution_period_laps,
    detect_incomplete_session,
    detect_missing_telemetry,
    detect_steward_and_confidence_exclusions,
    detect_timing_anomalies,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "2026"


def td(seconds: float) -> pd.Timedelta:
    return pd.Timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# derive_caution_periods
# ---------------------------------------------------------------------------

def _track_status(rows):
    return pd.DataFrame(rows, columns=["occurred_at", "status_code", "message"])


def test_caution_period_empty_input():
    assert derive_caution_periods(pd.DataFrame(columns=["occurred_at", "status_code", "message"])).empty


def test_caution_period_simple_yellow():
    events = _track_status([
        (td(0), "1", "AllClear"),
        (td(100), "2", "Yellow"),
        (td(140), "1", "AllClear"),
    ])
    periods = derive_caution_periods(events)
    assert len(periods) == 1
    assert periods.iloc[0]["period_type"] == "yellow"
    assert periods.iloc[0]["start_time"] == td(100)
    assert periods.iloc[0]["end_time"] == td(140)


def test_caution_period_escalation_stays_one_period():
    """Yellow escalating to VSC for the same incident, without an
    intervening AllClear, must not be split into two periods."""
    events = _track_status([
        (td(0), "1", "AllClear"),
        (td(100), "2", "Yellow"),
        (td(105), "6", "VSCDeployed"),
        (td(140), "7", "VSCEnding"),
        (td(150), "1", "AllClear"),
    ])
    periods = derive_caution_periods(events)
    assert len(periods) == 1
    assert periods.iloc[0]["period_type"] == "yellow"  # labeled by the opening code
    assert periods.iloc[0]["start_time"] == td(100)
    assert periods.iloc[0]["end_time"] == td(150)


def test_caution_period_never_closed_gets_null_end():
    events = _track_status([
        (td(0), "1", "AllClear"),
        (td(500), "5", "RedFlag"),
    ])
    periods = derive_caution_periods(events)
    assert len(periods) == 1
    assert periods.iloc[0]["period_type"] == "red_flag"
    assert periods.iloc[0]["end_time"] is None


def test_caution_period_two_separate_incidents():
    events = _track_status([
        (td(0), "1", "AllClear"),
        (td(100), "2", "Yellow"),
        (td(110), "1", "AllClear"),
        (td(300), "4", "SafetyCar"),
        (td(400), "1", "AllClear"),
    ])
    periods = derive_caution_periods(events)
    assert len(periods) == 2
    assert list(periods["period_type"]) == ["yellow", "safety_car"]


# ---------------------------------------------------------------------------
# detect_caution_period_laps
# ---------------------------------------------------------------------------

def _laps(rows):
    cols = ["driver_id", "lap_number", "lap_start_time", "lap_time", "sector1_time",
            "sector2_time", "sector3_time", "deleted", "deleted_reason", "pit_in_time",
            "pit_out_time", "is_accurate"]
    return pd.DataFrame(rows, columns=cols)


def _clean_lap(driver_id="ver", lap_number=1, lap_start_time=td(0), lap_time=td(90),
               s1=td(30), s2=td(30), s3=td(30), deleted=False, deleted_reason=None,
               pit_in=None, pit_out=None, is_accurate=True):
    return {
        "driver_id": driver_id, "lap_number": lap_number, "lap_start_time": lap_start_time,
        "lap_time": lap_time, "sector1_time": s1, "sector2_time": s2, "sector3_time": s3,
        "deleted": deleted, "deleted_reason": deleted_reason, "pit_in_time": pit_in,
        "pit_out_time": pit_out, "is_accurate": is_accurate,
    }


def test_lap_fully_inside_caution_period_flagged():
    laps = _laps([_clean_lap(lap_start_time=td(105), lap_time=td(90))])  # 105 -> 195
    periods = pd.DataFrame([{"period_type": "safety_car", "start_time": td(100), "end_time": td(300)}])
    out = detect_caution_period_laps(laps, periods)
    assert len(out) == 1
    assert out.iloc[0]["category"] == "caution_period"


def test_lap_entirely_before_period_not_flagged():
    laps = _laps([_clean_lap(lap_start_time=td(0), lap_time=td(50))])  # 0 -> 50
    periods = pd.DataFrame([{"period_type": "yellow", "start_time": td(100), "end_time": td(140)}])
    assert detect_caution_period_laps(laps, periods).empty


def test_lap_overlapping_open_ended_period_flagged():
    laps = _laps([_clean_lap(lap_start_time=td(500), lap_time=td(90))])
    periods = pd.DataFrame([{"period_type": "red_flag", "start_time": td(400), "end_time": None}])
    out = detect_caution_period_laps(laps, periods)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# detect_steward_and_confidence_exclusions
# ---------------------------------------------------------------------------

def test_clean_lap_produces_no_exclusions():
    laps = _laps([_clean_lap()])
    assert detect_steward_and_confidence_exclusions(laps).empty


def test_deleted_lap_flagged_with_reason():
    laps = _laps([_clean_lap(deleted=True, deleted_reason="TRACK LIMITS AT TURN 4")])
    out = detect_steward_and_confidence_exclusions(laps)
    assert len(out) == 1
    assert out.iloc[0]["category"] == "steward_deleted"
    assert "TRACK LIMITS" in out.iloc[0]["reason"]


def test_deleted_lap_with_no_reason_gets_fallback_text():
    laps = _laps([_clean_lap(deleted=True, deleted_reason=None)])
    out = detect_steward_and_confidence_exclusions(laps)
    assert len(out) == 1
    assert out.iloc[0]["reason"]  # non-empty fallback, not blank/None


def test_pit_in_and_out_laps_both_flagged_independently():
    laps = _laps([_clean_lap(pit_in=td(2500)), _clean_lap(lap_number=2, pit_out=td(2600))])
    out = detect_steward_and_confidence_exclusions(laps)
    assert len(out) == 2
    assert set(out["category"]) == {"pit_lap"}


def test_low_confidence_lap_flagged():
    laps = _laps([_clean_lap(is_accurate=False)])
    out = detect_steward_and_confidence_exclusions(laps)
    assert len(out) == 1
    assert out.iloc[0]["category"] == "low_confidence"


# ---------------------------------------------------------------------------
# detect_timing_anomalies
# ---------------------------------------------------------------------------

def test_normal_laps_no_anomalies():
    laps = _laps([_clean_lap(lap_time=td(90), s1=td(30), s2=td(30), s3=td(30)),
                   _clean_lap(lap_number=2, lap_time=td(91), s1=td(30), s2=td(31), s3=td(30))])
    assert detect_timing_anomalies(laps).empty


def test_implausibly_fast_lap_flagged():
    """A lap timed at less than half the session's real fastest lap is a
    timing glitch, not a real lap -- e.g. session fastest is 90s, this one
    is 10s."""
    laps = _laps([
        _clean_lap(lap_number=1, lap_time=td(90), s1=td(30), s2=td(30), s3=td(30)),
        _clean_lap(lap_number=2, lap_time=td(10), s1=td(3), s2=td(4), s3=td(3)),
    ])
    out = detect_timing_anomalies(laps)
    flagged = out[out["lap_number"] == 2]
    assert len(flagged) == 1
    assert "implausible pace" in flagged.iloc[0]["reason"]


def test_sector_sum_mismatch_flagged():
    """Sectors sum to 60s but lap_time says 90s -- internally inconsistent
    timing data, independent of whether 90s itself looks plausible."""
    laps = _laps([_clean_lap(lap_time=td(90), s1=td(20), s2=td(20), s3=td(20))])
    out = detect_timing_anomalies(laps)
    assert len(out) == 1
    assert "sum to" in out.iloc[0]["reason"]


def test_missing_lap_time_does_not_crash():
    laps = _laps([_clean_lap(lap_time=pd.NaT)])
    assert detect_timing_anomalies(laps).empty


def test_missing_sectors_skips_sector_check_but_not_pace_check():
    laps = _laps([
        _clean_lap(lap_number=1, lap_time=td(90), s1=td(30), s2=td(30), s3=td(30)),
        _clean_lap(lap_number=2, lap_time=td(5), s1=pd.NaT, s2=pd.NaT, s3=pd.NaT),
    ])
    out = detect_timing_anomalies(laps)
    flagged = out[out["lap_number"] == 2]
    assert len(flagged) == 1
    assert "implausible pace" in flagged.iloc[0]["reason"]


# ---------------------------------------------------------------------------
# detect_incomplete_session -- real fixtures + synthetic malformed ones
# ---------------------------------------------------------------------------

def _session_status(rows):
    return pd.DataFrame(rows, columns=["occurred_at", "status"])


def test_real_session_with_aborted_but_reaching_ends_is_not_incomplete():
    """Monaco GP practice_1 genuinely hits 'Aborted' twice mid-session and
    still finishes normally -- this must NOT be flagged incomplete, only as
    having red-flag interruptions."""
    df = pd.read_parquet(FIXTURE_ROOT / "06_monaco_grand_prix" / "practice_1" / "session_status.parquet")
    events = pd.DataFrame({"occurred_at": df["Time"], "status": df["Status"]})
    out = detect_incomplete_session(events)
    assert "incomplete_session" not in set(out["issue_type"])
    red_flag_rows = out[out["issue_type"] == "red_flag_interruption"]
    assert len(red_flag_rows) == 1
    assert "2 time(s)" in red_flag_rows.iloc[0]["detail"]


def test_session_that_never_reaches_ends_is_incomplete():
    events = _session_status([(td(0), "Inactive"), (td(60), "Started"), (td(600), "Aborted")])
    out = detect_incomplete_session(events)
    assert "incomplete_session" in set(out["issue_type"])


def test_empty_session_status_is_incomplete():
    out = detect_incomplete_session(pd.DataFrame(columns=["occurred_at", "status"]))
    assert "incomplete_session" in set(out["issue_type"])


def test_normal_session_with_no_red_flags_has_no_flags_at_all():
    events = _session_status([(td(0), "Inactive"), (td(60), "Started"), (td(6000), "Finished"),
                               (td(6100), "Finalised"), (td(6200), "Ends")])
    assert detect_incomplete_session(events).empty


# ---------------------------------------------------------------------------
# detect_missing_telemetry
# ---------------------------------------------------------------------------

def _results(driver_ids):
    return pd.DataFrame({"driver_id": driver_ids})


def _telemetry(rows, cols):
    return pd.DataFrame(rows, columns=["driver_id"] + list(cols))


def test_driver_with_full_telemetry_flagged_clean():
    results = _results(["ver", "nor"])
    car = _telemetry([("ver", 10000, 250, 7, 0.9, False, 0), ("nor", 10500, 260, 8, 1.0, False, 0)],
                      ["rpm", "speed", "n_gear", "throttle", "brake", "drs"])
    pos = _telemetry([("ver", 100, 200, 0), ("nor", 110, 210, 0)], ["x", "y", "z"])
    out = detect_missing_telemetry(results, car, pos)
    assert out.empty


def test_driver_with_zero_telemetry_rows_flagged():
    results = _results(["ver", "per"])
    car = _telemetry([("ver", 10000, 250, 7, 0.9, False, 0)],
                      ["rpm", "speed", "n_gear", "throttle", "brake", "drs"])
    pos = _telemetry([("ver", 100, 200, 0)], ["x", "y", "z"])
    out = detect_missing_telemetry(results, car, pos)
    per_issues = set(out[out["driver_id"] == "per"]["issue_type"])
    assert "missing_car_telemetry" in per_issues
    assert "missing_position_telemetry" in per_issues
    assert out[out["driver_id"] == "ver"].empty


def test_driver_with_dead_channel_flagged_but_not_missing_entirely():
    """This is the case that matters most: a driver has rows, so a naive
    "is there any data?" check would pass, but one channel (e.g. throttle
    sensor) is entirely null throughout -- a real, narrower failure mode."""
    results = _results(["ver"])
    car = _telemetry([("ver", 10000, 250, 7, None, False, 0), ("ver", 10500, 260, 8, None, False, 0)],
                      ["rpm", "speed", "n_gear", "throttle", "brake", "drs"])
    pos = _telemetry([("ver", 100, 200, 0)], ["x", "y", "z"])
    out = detect_missing_telemetry(results, car, pos)
    assert len(out) == 1
    assert out.iloc[0]["issue_type"] == "missing_channel"
    assert "throttle" in out.iloc[0]["detail"]


# ---------------------------------------------------------------------------
# integration: build_lap_exclusions / build_session_quality_flags
# ---------------------------------------------------------------------------

def test_build_lap_exclusions_combines_all_categories_without_crashing():
    laps = _laps([
        _clean_lap(lap_number=1),
        _clean_lap(lap_number=2, deleted=True, deleted_reason="TRACK LIMITS"),
        _clean_lap(lap_number=3, lap_start_time=td(200), lap_time=td(5), s1=None, s2=None, s3=None),
    ])
    periods = pd.DataFrame([{"period_type": "safety_car", "start_time": td(150), "end_time": td(400)}])
    out = build_lap_exclusions(laps, periods)
    categories = set(out["category"])
    assert "steward_deleted" in categories
    assert "caution_period" in categories
    assert "timing_anomaly" in categories


def test_build_lap_exclusions_empty_inputs_return_empty_frame():
    out = build_lap_exclusions(_laps([]), pd.DataFrame(columns=["period_type", "start_time", "end_time"]))
    assert out.empty
    assert list(out.columns) == ["driver_id", "lap_number", "category", "reason"]


def test_build_session_quality_flags_combines_categories():
    events = _session_status([(td(0), "Inactive"), (td(60), "Started"), (td(600), "Aborted")])
    results = _results(["ver"])
    car = pd.DataFrame(columns=["driver_id", "rpm"])
    pos = pd.DataFrame(columns=["driver_id", "x"])
    out = build_session_quality_flags(events, results, car, pos)
    assert "incomplete_session" in set(out["issue_type"])
    assert "missing_car_telemetry" in set(out["issue_type"])
