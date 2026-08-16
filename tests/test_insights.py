"""Unit tests for insights/rules.py's pure functions against hand-built
context dicts -- these operate on already-DataFrame-shaped inputs, no
database needed.

test_service_integration_runs_and_writes_insight_findings at the bottom is
different: it runs the full read-from-Postgres -> evaluate rules ->
write-to-insight_findings pipeline against a real ingested+analyzed
session, gated on DATABASE_URL like tests/test_analytics_service.py's
equivalent.
"""
import os

import pandas as pd
import pytest

from insights.rules import (
    _name,
    evaluate_all_rules,
    rule_braking_efficiency_vs_teammate,
    rule_pace_consistency_vs_teammate,
    rule_sector_time_vs_teammate,
    rule_stint_degradation_vs_field,
    rule_time_left_on_table,
)


def _degradation_rows(rows):
    cols = ["driver_id", "stint_number", "slope_s_per_lap", "confidence", "team_id"]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# rule_stint_degradation_vs_field
# ---------------------------------------------------------------------------

def test_degradation_rule_fires_when_red_bull_well_above_field_average():
    degradation = _degradation_rows([
        ("ver", 1, 0.30, "high", "red_bull"),   # ~2x field average -> high
        ("nor", 1, 0.14, "high", "mclaren"),
        ("lec", 1, 0.16, "high", "ferrari"),
    ])
    context = {"session_id": 1, "degradation_with_team": degradation}
    out = rule_stint_degradation_vs_field(context)
    assert len(out) == 1
    assert out[0]["subject_driver_id"] == "ver"
    assert out[0]["severity"] == "high"
    assert out[0]["compared_against_type"] == "field_avg"


def test_degradation_rule_silent_when_close_to_field_average():
    degradation = _degradation_rows([
        ("ver", 1, 0.16, "high", "red_bull"),
        ("nor", 1, 0.14, "high", "mclaren"),
        ("lec", 1, 0.15, "high", "ferrari"),
    ])
    context = {"session_id": 1, "degradation_with_team": degradation}
    assert rule_stint_degradation_vs_field(context) == []


def test_degradation_rule_ignores_low_confidence_stints():
    degradation = _degradation_rows([
        ("ver", 1, 0.40, "low", "red_bull"),   # would fire, but not trustworthy
        ("nor", 1, 0.14, "high", "mclaren"),
    ])
    context = {"session_id": 1, "degradation_with_team": degradation}
    assert rule_stint_degradation_vs_field(context) == []


def test_degradation_rule_empty_input_returns_empty():
    context = {"session_id": 1, "degradation_with_team": _degradation_rows([])}
    assert rule_stint_degradation_vs_field(context) == []


# ---------------------------------------------------------------------------
# rule_sector_time_vs_teammate
# ---------------------------------------------------------------------------

def _sector_laps(rows):
    cols = ["driver_id", "lap_number", "sector1_time_s", "sector2_time_s", "sector3_time_s"]
    return pd.DataFrame(rows, columns=cols)


def test_teammate_rule_fires_for_consistent_sector_gap():
    laps = _sector_laps([
        ("ver", 1, 30.0, 35.0, 28.0),
        ("per", 1, 30.5, 35.6, 28.0),   # +0.6s in sector 2
        ("ver", 2, 30.1, 35.1, 28.1),
        ("per", 2, 30.6, 35.7, 28.1),
        ("ver", 3, 30.0, 35.0, 28.0),
        ("per", 3, 30.5, 35.6, 28.0),
    ])
    context = {"session_id": 1, "red_bull_driver_ids": ["per", "ver"], "red_bull_sector_laps": laps}
    out = rule_sector_time_vs_teammate(context)
    sector2 = [f for f in out if f["subject"]["sector"] == "sector2"]
    assert len(sector2) == 1
    assert sector2[0]["subject_driver_id"] == "per"
    assert sector2[0]["compared_against_driver_id"] == "ver"
    assert sector2[0]["severity"] == "high"


def test_teammate_rule_needs_exactly_two_red_bull_drivers():
    laps = _sector_laps([("ver", 1, 30.0, 35.0, 28.0)])
    context = {"session_id": 1, "red_bull_driver_ids": ["ver"], "red_bull_sector_laps": laps}
    assert rule_sector_time_vs_teammate(context) == []


def test_teammate_rule_needs_at_least_three_shared_laps():
    laps = _sector_laps([
        ("ver", 1, 30.0, 35.0, 28.0),
        ("per", 1, 30.6, 35.6, 28.6),
        ("ver", 2, 30.0, 35.0, 28.0),
        ("per", 2, 30.6, 35.6, 28.6),
    ])
    context = {"session_id": 1, "red_bull_driver_ids": ["per", "ver"], "red_bull_sector_laps": laps}
    assert rule_sector_time_vs_teammate(context) == []


def test_teammate_rule_message_uses_full_names_when_available():
    laps = _sector_laps([
        ("ver", 1, 30.0, 35.0, 28.0),
        ("per", 1, 30.5, 35.6, 28.0),
        ("ver", 2, 30.1, 35.1, 28.1),
        ("per", 2, 30.6, 35.7, 28.1),
        ("ver", 3, 30.0, 35.0, 28.0),
        ("per", 3, 30.5, 35.6, 28.0),
    ])
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["per", "ver"],
        "red_bull_sector_laps": laps,
        "driver_names": {"ver": "Max Verstappen", "per": "Sergio Perez"},
    }
    out = rule_sector_time_vs_teammate(context)
    sector2 = [f for f in out if f["subject"]["sector"] == "sector2"][0]
    assert "Sergio Perez" in sector2["message"]
    assert "Max Verstappen" in sector2["message"]


# ---------------------------------------------------------------------------
# _name()
# ---------------------------------------------------------------------------

def test_name_resolves_from_driver_names():
    assert _name({"driver_names": {"ver": "Max Verstappen"}}, "ver") == "Max Verstappen"


def test_name_falls_back_to_raw_id_when_unmapped():
    assert _name({"driver_names": {"ver": "Max Verstappen"}}, "unknown") == "unknown"


def test_name_falls_back_to_raw_id_when_context_has_no_driver_names():
    assert _name({"session_id": 1}, "ver") == "ver"


# ---------------------------------------------------------------------------
# rule_time_left_on_table
# ---------------------------------------------------------------------------

def test_time_left_on_table_rule_fires_above_threshold():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["ver", "per"],
        "time_left_on_table_by_driver": {"ver": 0.9, "per": 0.1},
    }
    out = rule_time_left_on_table(context)
    assert len(out) == 1
    assert out[0]["subject_driver_id"] == "ver"
    assert out[0]["compared_against_type"] == "session_optimal"


def test_time_left_on_table_rule_silent_below_threshold():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["ver"],
        "time_left_on_table_by_driver": {"ver": 0.1},
    }
    assert rule_time_left_on_table(context) == []


# ---------------------------------------------------------------------------
# rule_braking_efficiency_vs_teammate
# ---------------------------------------------------------------------------

def test_braking_efficiency_rule_fires_for_meaningful_gap():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["per", "ver"],
        "red_bull_brake_pct_by_driver": {"ver": 12.0, "per": 18.0},  # per: 50% more
    }
    out = rule_braking_efficiency_vs_teammate(context)
    assert len(out) == 1
    assert out[0]["subject_driver_id"] == "per"
    assert out[0]["compared_against_driver_id"] == "ver"
    assert out[0]["severity"] == "high"


def test_braking_efficiency_rule_silent_for_small_gap():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["per", "ver"],
        "red_bull_brake_pct_by_driver": {"ver": 15.0, "per": 15.5},
    }
    assert rule_braking_efficiency_vs_teammate(context) == []


def test_braking_efficiency_rule_needs_both_drivers():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["ver"],
        "red_bull_brake_pct_by_driver": {"ver": 15.0},
    }
    assert rule_braking_efficiency_vs_teammate(context) == []


# ---------------------------------------------------------------------------
# rule_pace_consistency_vs_teammate
# ---------------------------------------------------------------------------

def _stint_laps(rows):
    return pd.DataFrame(rows, columns=["driver_id", "stint_number", "lap_time_s"])


def test_consistency_rule_fires_for_higher_variance():
    rows = []
    for t in [90.0, 90.1, 89.9, 90.0, 90.05]:
        rows.append(("ver", 1, t))
    for t in [90.0, 91.5, 88.7, 90.9, 89.3]:
        rows.append(("per", 1, t))
    context = {"session_id": 1, "red_bull_driver_ids": ["per", "ver"], "red_bull_stint_laps": _stint_laps(rows)}
    out = rule_pace_consistency_vs_teammate(context)
    assert len(out) == 1
    assert out[0]["subject_driver_id"] == "per"
    assert out[0]["compared_against_driver_id"] == "ver"
    assert out[0]["subject"] == {"stint_number": 1}


def test_consistency_rule_silent_for_similar_variance():
    rows = []
    for t in [90.0, 90.2, 89.8, 90.1, 89.9]:
        rows.append(("ver", 1, t))
    for t in [90.1, 90.3, 89.7, 90.0, 90.2]:
        rows.append(("per", 1, t))
    context = {"session_id": 1, "red_bull_driver_ids": ["per", "ver"], "red_bull_stint_laps": _stint_laps(rows)}
    assert rule_pace_consistency_vs_teammate(context) == []


def test_consistency_rule_needs_minimum_laps_per_stint():
    rows = [("ver", 1, 90.0), ("ver", 1, 90.1), ("per", 1, 90.0), ("per", 1, 95.0)]
    context = {"session_id": 1, "red_bull_driver_ids": ["per", "ver"], "red_bull_stint_laps": _stint_laps(rows)}
    assert rule_pace_consistency_vs_teammate(context) == []


def test_time_left_on_table_rule_missing_data_skipped():
    context = {"session_id": 1, "red_bull_driver_ids": ["ver"], "time_left_on_table_by_driver": {}}
    assert rule_time_left_on_table(context) == []


# ---------------------------------------------------------------------------
# evaluate_all_rules
# ---------------------------------------------------------------------------

def test_evaluate_all_rules_aggregates_across_rules():
    context = {
        "session_id": 1,
        "red_bull_driver_ids": ["ver"],
        "degradation_with_team": _degradation_rows([]),
        "red_bull_sector_laps": _sector_laps([]),
        "time_left_on_table_by_driver": {"ver": 0.9},
        "red_bull_brake_pct_by_driver": {},
        "red_bull_stint_laps": _stint_laps([]),
    }
    out = evaluate_all_rules(context)
    assert len(out) == 1
    assert out[0]["finding_type"] == "time_left_on_table"


# ---------------------------------------------------------------------------
# full-service integration (real ingested + analyzed session, gated on DATABASE_URL)
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set -- integration test needs a live Postgres")
def test_service_integration_runs_and_writes_insight_findings():
    import psycopg2

    from insights.service import run_insights_for_session

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("select id from public.sessions order by id limit 1")
            row = cur.fetchone()
            if row is None:
                pytest.skip("no ingested sessions in target database")
            session_id = row[0]

        counts = run_insights_for_session(conn, session_id)
        assert isinstance(counts, dict)

        with conn.cursor() as cur:
            cur.execute("select count(*) from public.insight_findings where session_id = %s", (session_id,))
            db_count = cur.fetchone()[0]
        assert db_count == sum(counts.values())
    finally:
        conn.close()
