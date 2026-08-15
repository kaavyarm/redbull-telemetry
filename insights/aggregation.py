"""Team/field aggregation on top of analytics/'s per-driver outputs, joined
through session_results.team_id -- the only place team affiliation lives
per session (a driver's team can change season to season, so nothing on
drivers/laps/stints carries it directly; see supabase/schema.sql). This is
a different concern from analytics/: aggregating already-computed
per-driver numbers, not new low-level telemetry math.
"""
import pandas as pd

RED_BULL_TEAM_ID = "red_bull"


def join_team_ids(df: pd.DataFrame, session_results: pd.DataFrame) -> pd.DataFrame:
    """Attach team_id to any per-driver DataFrame via session_results."""
    return df.merge(session_results[["driver_id", "team_id"]], on="driver_id", how="left")


def compute_field_average_degradation(degradation_with_team: pd.DataFrame,
                                       exclude_team_id: str = RED_BULL_TEAM_ID) -> float | None:
    """Mean slope_s_per_lap across trustworthy stints (confidence in
    medium/high), excluding a team -- reuses degradation.py's own
    confidence classification rather than re-deriving trustworthiness."""
    if degradation_with_team.empty:
        return None
    trustworthy = degradation_with_team[degradation_with_team["confidence"].isin(["medium", "high"])]
    field = trustworthy[trustworthy["team_id"] != exclude_team_id]
    if field.empty:
        return None
    return float(field["slope_s_per_lap"].mean())
