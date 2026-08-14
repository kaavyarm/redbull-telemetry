"""Stint degradation modeling: a proper linear regression (slope, intercept,
R-squared, standard error of the slope) per stint, richer than the SQL
`stint_performance` view's `regr_slope()` -- which gives only the slope, no
way to tell a confident 20-lap trend from a noisy 3-lap one. That
confidence classification is the actual reason this belongs in Python:
computing standard error and deciding what counts as "trustworthy" isn't a
SQL aggregate's job.

Also deliberately uses lap-number-within-stint (1, 2, 3, ...) as the
regression's x-axis rather than the absolute in-session lap number the SQL
view uses -- tyre degradation is a function of tyre age, not race lap
count, and the two only coincide for a driver's first stint.
"""
import numpy as np
import pandas as pd


def _seconds(td) -> float:
    return td.total_seconds() if pd.notna(td) else float("nan")


def _linreg_stats(x: np.ndarray, y: np.ndarray) -> dict | None:
    n = len(x)
    if n < 2:
        return None
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mean_x, mean_y = x.mean(), y.mean()
    sxx = ((x - mean_x) ** 2).sum()
    if sxx == 0:
        return None  # degenerate: every point at the same x
    sxy = ((x - mean_x) * (y - mean_y)).sum()
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = y - (intercept + slope * x)
    sse = float((residuals ** 2).sum())
    sst = float(((y - mean_y) ** 2).sum())
    r_squared = (1 - sse / sst) if sst > 0 else float("nan")
    se_slope = float(np.sqrt(sse / (n - 2)) / np.sqrt(sxx)) if n > 2 else float("nan")
    return {
        "slope_s_per_lap": float(slope),
        "intercept_s": float(intercept),
        "r_squared": r_squared,
        "se_slope": se_slope,
        "n_laps": n,
    }


def _confidence(stats: dict | None) -> str:
    if stats is None or stats["n_laps"] < 3 or pd.isna(stats["r_squared"]):
        return "insufficient_data"
    r2 = stats["r_squared"]
    if r2 >= 0.5:
        return "high"
    if r2 >= 0.2:
        return "medium"
    return "low"


def compute_stint_degradation(laps: pd.DataFrame, lap_exclusions: pd.DataFrame) -> pd.DataFrame:
    """laps must include: id, driver_id, stint_id, lap_number, lap_time, and
    the stint's own identifying columns already joined on
    (driver_id, stint_number, lap_start, lap_end) -- see
    analytics/service.py for how this gets assembled from the base tables."""
    excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()

    rows = []
    group_cols = ["driver_id", "stint_number"]
    for (driver_id, stint_number), g in laps.groupby(group_cols):
        clean = g[~g["id"].isin(excluded_ids)].sort_values("lap_number")
        clean = clean.dropna(subset=["lap_time"])
        if clean.empty:
            continue

        lap_in_stint = np.arange(1, len(clean) + 1)
        lap_time_s = clean["lap_time"].apply(_seconds).to_numpy()

        stats = _linreg_stats(lap_in_stint, lap_time_s)
        confidence = _confidence(stats)

        rows.append({
            "driver_id": driver_id,
            "stint_number": int(stint_number),
            "compound": clean["compound"].iloc[0] if "compound" in clean.columns else None,
            "clean_lap_count": len(clean),
            "slope_s_per_lap": stats["slope_s_per_lap"] if stats else None,
            "intercept_s": stats["intercept_s"] if stats else None,
            "r_squared": stats["r_squared"] if stats else None,
            "se_slope": stats["se_slope"] if stats else None,
            "confidence": confidence,
        })
    return pd.DataFrame(rows)
