"""Unit tests for ingest/tiering.py -- pure functions over DataFrames, no
database needed."""
import pandas as pd

from ingest.tiering import determine_telemetry_tier


def _session_results(rows):
    cols = ["driver_id", "team_id", "position"]
    return pd.DataFrame(rows, columns=cols)


def _laps(rows):
    cols = ["driver_id", "lap_time", "deleted"]
    return pd.DataFrame(rows, columns=cols)


def td(seconds):
    return pd.Timedelta(seconds=seconds)


def test_race_tier_includes_red_bull_and_top_finishers():
    results = _session_results([
        ("ver", "red_bull", 1), ("per", "red_bull", 2),
        ("nor", "mclaren", 3), ("lec", "ferrari", 4), ("ham", "ferrari", 5),
        ("rus", "mercedes", 6), ("alo", "aston_martin", 7), ("gas", "alpine", 8),
        ("oco", "haas", 9), ("str", "aston_martin", 10),
    ])
    tier = determine_telemetry_tier(results, pd.DataFrame(), "race", rival_tier_size=3)
    assert {"ver", "per"} <= tier
    assert tier == {"ver", "per", "nor", "lec", "ham"}


def test_practice_tier_uses_fastest_lap_not_position():
    results = _session_results([
        ("ver", "red_bull", None), ("per", "red_bull", None),
        ("nor", "mclaren", None), ("lec", "ferrari", None),
    ])
    laps = _laps([
        ("nor", td(90.0), False),
        ("lec", td(89.5), False),
        ("lec", td(200.0), True),  # deleted -- should not count as lec's best
    ])
    tier = determine_telemetry_tier(results, laps, "practice_2", rival_tier_size=1)
    assert tier == {"ver", "per", "lec"}


def test_empty_session_results_returns_empty_tier():
    assert determine_telemetry_tier(_session_results([]), _laps([]), "race") == set()


def test_rival_tier_size_caps_rival_count():
    results = _session_results([
        ("ver", "red_bull", 1),
        ("a", "team_a", 2), ("b", "team_b", 3), ("c", "team_c", 4), ("d", "team_d", 5),
    ])
    tier = determine_telemetry_tier(results, pd.DataFrame(), "qualifying", rival_tier_size=2)
    assert tier == {"ver", "a", "b"}
