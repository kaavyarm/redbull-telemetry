"""Decides which drivers get full car/position telemetry written for a
session -- Red Bull's own drivers plus that session's closest rivals, with
everyone else still getting laps/results/stints/setup_revisions (just not
the two high-volume telemetry tables). This reduces database write/storage
volume, not FastF1 fetch time: session.load() always pulls the whole
session regardless, since FastF1 has no per-driver-selective fetch -- the
filtering happens on the already-loaded, already-transformed DataFrames,
right before ingest/db.py::write_session's bulk insert.
"""
import pandas as pd

RED_BULL_TEAM_ID = "red_bull"
DEFAULT_RIVAL_TIER_SIZE = 6


def determine_telemetry_tier(session_results: pd.DataFrame, laps: pd.DataFrame, session_type: str,
                              rival_tier_size: int = DEFAULT_RIVAL_TIER_SIZE) -> set[str]:
    if session_results.empty:
        return set()

    red_bull_ids = set(session_results.loc[session_results["team_id"] == RED_BULL_TEAM_ID, "driver_id"])

    non_red_bull = session_results[session_results["team_id"] != RED_BULL_TEAM_ID]
    if session_type.startswith("practice"):
        rival_ids = _rivals_by_best_lap(non_red_bull, laps, rival_tier_size)
    else:
        rival_ids = _rivals_by_classification(non_red_bull, rival_tier_size)

    return red_bull_ids | rival_ids


def _rivals_by_classification(non_red_bull: pd.DataFrame, rival_tier_size: int) -> set[str]:
    ranked = non_red_bull.dropna(subset=["position"]).sort_values("position")
    return set(ranked["driver_id"].head(rival_tier_size))


def _rivals_by_best_lap(non_red_bull: pd.DataFrame, laps: pd.DataFrame, rival_tier_size: int) -> set[str]:
    # Position/classified_position isn't meaningful in practice sessions --
    # fastest clean lap is the closest available proxy for "who's a rival
    # this session."
    if laps.empty:
        return set()
    clean = laps[~laps.get("deleted", False).fillna(False)].dropna(subset=["lap_time"])
    candidates = clean[clean["driver_id"].isin(non_red_bull["driver_id"])]
    if candidates.empty:
        return set()
    best_by_driver = candidates.groupby("driver_id")["lap_time"].min().sort_values()
    return set(best_by_driver.head(rival_tier_size).index)
