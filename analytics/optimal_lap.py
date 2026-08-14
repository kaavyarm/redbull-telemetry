"""Optimal-lap estimation: the classic motorsport "theoretical best lap" --
sum each sector's single fastest recorded time, independent of which lap it
came from. Always faster than (or equal to) any single actual lap, since no
driver puts their three best sectors together in the same lap every time.

Simple enough that it could live in SQL as three MIN()s, but it belongs
alongside the other analytics-service metrics because it's part of the
same batch output and the same "how much time was left on the table"
framing as degradation modeling -- and because building it here means it
shares the same clean-lap filtering logic as everything else in this
package rather than re-deriving lap_exclusions membership in a view.
"""
import pandas as pd


def _seconds(td) -> float:
    return td.total_seconds() if pd.notna(td) else float("nan")


def _clean_laps(laps: pd.DataFrame, lap_exclusions: pd.DataFrame) -> pd.DataFrame:
    excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()
    return laps[~laps["id"].isin(excluded_ids)]


def _best_sectors(clean: pd.DataFrame) -> dict:
    s1 = clean["sector1_time"].dropna()
    s2 = clean["sector2_time"].dropna()
    s3 = clean["sector3_time"].dropna()
    return {
        "best_sector1_s": _seconds(s1.min()) if not s1.empty else None,
        "best_sector2_s": _seconds(s2.min()) if not s2.empty else None,
        "best_sector3_s": _seconds(s3.min()) if not s3.empty else None,
    }


def compute_driver_optimal_laps(laps: pd.DataFrame, lap_exclusions: pd.DataFrame) -> pd.DataFrame:
    """One row per driver: their own best sectors summed vs. their own best
    actual lap. Only laps with all three sectors AND a lap_time recorded are
    eligible for "actual best lap" (matches what a driver could really see
    on a timing screen); best-sector search uses any clean lap with that
    sector present, even if the lap's other sectors are missing."""
    clean = _clean_laps(laps, lap_exclusions)
    rows = []
    for driver_id in laps["driver_id"].unique():
        g = clean[clean["driver_id"] == driver_id]
        best = _best_sectors(g)
        complete = g.dropna(subset=["lap_time"])
        actual_best_s = _seconds(complete["lap_time"].min()) if not complete.empty else None

        optimal_s = None
        if all(v is not None for v in best.values()):
            optimal_s = best["best_sector1_s"] + best["best_sector2_s"] + best["best_sector3_s"]

        time_left_s = None
        if optimal_s is not None and actual_best_s is not None:
            time_left_s = actual_best_s - optimal_s

        rows.append({
            "driver_id": driver_id,
            **best,
            "optimal_lap_s": optimal_s,
            "actual_best_lap_s": actual_best_s,
            "time_left_on_table_s": time_left_s,
        })
    return pd.DataFrame(rows)


def compute_session_optimal_lap(laps: pd.DataFrame, lap_exclusions: pd.DataFrame) -> dict:
    """Session-wide "ultimate lap" -- best sector from anyone, same shape as
    compute_driver_optimal_laps' per-row output but not tied to one driver."""
    clean = _clean_laps(laps, lap_exclusions)
    best = _best_sectors(clean)
    complete = clean.dropna(subset=["lap_time"])
    actual_best_s = _seconds(complete["lap_time"].min()) if not complete.empty else None

    optimal_s = None
    if all(v is not None for v in best.values()):
        optimal_s = best["best_sector1_s"] + best["best_sector2_s"] + best["best_sector3_s"]

    time_left_s = actual_best_s - optimal_s if (optimal_s is not None and actual_best_s is not None) else None

    return {
        **best,
        "optimal_lap_s": optimal_s,
        "actual_best_lap_s": actual_best_s,
        "time_left_on_table_s": time_left_s,
    }
