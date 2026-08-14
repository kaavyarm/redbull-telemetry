"""Independent pandas reference implementation of supabase/views.sql, used
only by tests/test_analytics_parity.py to prove the SQL views are
computing what they claim to before any downstream consumer is allowed to
trust them.

Two pandas behaviors here deliberately deviate from the "obvious" pandas
idiom because they don't match SQL's window-function semantics:

- `Series.cummin()` leaves NaN at the exact row where the input was NaN,
  rather than carrying the last valid minimum forward through it. SQL's
  `MIN(...) OVER (ROWS UNBOUNDED PRECEDING)` does carry it forward (the
  current row contributing NULL to the frame doesn't blank out the frame's
  aggregate). Fixed by `.cummin().ffill()`.
- `Series.rank()` leaves NaN unranked by default. SQL's `RANK() OVER (ORDER
  BY x)` with Postgres's default NULLS LAST still assigns NULLs a real
  (tied, trailing) rank. Fixed by `na_option="bottom"`.
"""
import numpy as np
import pandas as pd


def _seconds(td: pd.Series) -> pd.Series:
    return td.dt.total_seconds()


def _regr_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Matches Postgres's regr_slope(Y, X) = covar_pop(Y, X) / var_pop(X)
    exactly (both are population, not sample, covariance/variance) --
    returns NaN under the same condition Postgres returns NULL: fewer than
    2 points, or every x value identical (var_pop(X) == 0)."""
    if len(x) < 2:
        return np.nan
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mean_x, mean_y = x.mean(), y.mean()
    var_x = ((x - mean_x) ** 2).mean()
    if var_x == 0:
        return np.nan
    covar_xy = ((x - mean_x) * (y - mean_y)).mean()
    return covar_xy / var_x


def reference_lap_time_evolution(laps: pd.DataFrame, lap_exclusions: pd.DataFrame) -> pd.DataFrame:
    """laps must have columns: id, session_id, driver_id, lap_number,
    stint_id, compound, lap_time (Timedelta). lap_exclusions: lap_id,
    category."""
    df = laps.sort_values(["session_id", "driver_id", "lap_number"]).reset_index(drop=True)

    excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()
    df["is_excluded"] = df["id"].isin(excluded_ids)

    df["lap_time_s"] = _seconds(df["lap_time"])

    df["rank_in_lap"] = df.groupby(["session_id", "lap_number"])["lap_time_s"] \
        .rank(method="min", na_option="bottom")

    df["prev_lap_time_s"] = df.groupby(["session_id", "driver_id"])["lap_time_s"].shift(1)
    df["delta_to_prev_lap_s"] = df["lap_time_s"] - df["prev_lap_time_s"]

    clean_time = df["lap_time_s"].where(~df["is_excluded"])
    grouped = clean_time.groupby([df["session_id"], df["driver_id"]])
    df["clean_personal_best_so_far_s"] = grouped.cummin().groupby([df["session_id"], df["driver_id"]]).ffill()
    df["delta_to_clean_personal_best_s"] = df["lap_time_s"] - df["clean_personal_best_so_far_s"]
    df = df.rename(columns={"id": "lap_id"})

    return df[[
        "lap_id", "session_id", "driver_id", "lap_number", "stint_id",
        "compound", "lap_time_s", "is_excluded", "rank_in_lap", "prev_lap_time_s", "delta_to_prev_lap_s",
        "clean_personal_best_so_far_s", "delta_to_clean_personal_best_s",
    ]]


def reference_stint_performance(laps: pd.DataFrame, stints: pd.DataFrame,
                                 setup_revisions: pd.DataFrame, lap_exclusions: pd.DataFrame) -> pd.DataFrame:
    """laps: id, stint_id, lap_number, lap_time. stints: id, session_id,
    driver_id, stint_number, lap_start, lap_end, setup_revision_id.
    setup_revisions: id, compound, tyre_life_start, fresh_tyre."""
    excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()

    # laps and stints both carry session_id/driver_id (a lap's own values
    # always match its stint's, by construction) -- keep only stint-specific
    # columns on the right side so the merge can't silently suffix session_id/
    # driver_id away into session_id_lap/session_id_stint.
    stint_cols = stints[["id", "stint_number", "lap_start", "lap_end", "setup_revision_id"]]
    merged = laps.merge(stint_cols, left_on="stint_id", right_on="id", suffixes=("", "_stint"))
    merged["lap_time_s"] = _seconds(merged["lap_time"])
    merged["is_excluded"] = merged["id"].isin(excluded_ids)

    rows = []
    group_cols = ["session_id", "driver_id", "stint_number", "lap_start", "lap_end", "setup_revision_id"]
    for key, g in merged.groupby(group_cols, dropna=False):
        clean = g[~g["is_excluded"]]
        slope = _regr_slope(clean["lap_number"].to_numpy(), clean["lap_time_s"].to_numpy())
        rows.append({
            **dict(zip(group_cols, key, strict=True)),
            "lap_count": len(g),
            "clean_lap_count": len(clean),
            "avg_clean_lap_time_s": clean["lap_time_s"].mean() if len(clean) else np.nan,
            "fastest_clean_lap_time_s": clean["lap_time_s"].min() if len(clean) else np.nan,
            "degradation_seconds_per_lap": slope,
        })
    out = pd.DataFrame(rows)

    sr = setup_revisions[["id", "compound", "tyre_life_start", "fresh_tyre"]].rename(
        columns={"id": "setup_revision_id"}
    )
    out = out.merge(sr, on="setup_revision_id", how="left")
    return out


def reference_setup_revision_deltas(stint_performance: pd.DataFrame) -> pd.DataFrame:
    df = stint_performance.sort_values(["session_id", "driver_id", "stint_number"]).reset_index(drop=True)
    grouped = df.groupby(["session_id", "driver_id"])
    df["prev_compound"] = grouped["compound"].shift(1)
    df["prev_avg_clean_lap_time_s"] = grouped["avg_clean_lap_time_s"].shift(1)
    df["pace_delta_vs_prev_stint_s"] = df["avg_clean_lap_time_s"] - df["prev_avg_clean_lap_time_s"]
    df["next_compound"] = grouped["compound"].shift(-1)
    return df[[
        "session_id", "driver_id", "stint_number", "compound", "tyre_life_start", "fresh_tyre",
        "clean_lap_count", "avg_clean_lap_time_s", "degradation_seconds_per_lap",
        "prev_compound", "prev_avg_clean_lap_time_s", "pace_delta_vs_prev_stint_s", "next_compound",
    ]]


def reference_compound_pace_summary(stint_performance: pd.DataFrame) -> pd.DataFrame:
    df = stint_performance[stint_performance["compound"].notna()]
    rows = []
    for (session_id, compound), g in df.groupby(["session_id", "compound"]):
        total_clean = g["clean_lap_count"].sum()
        if total_clean < 3:
            continue
        rows.append({
            "session_id": session_id,
            "compound": compound,
            "stint_count": len(g),
            "total_clean_laps": total_clean,
            "avg_pace_s": g["avg_clean_lap_time_s"].mean(),
            "best_lap_time_s": g["fastest_clean_lap_time_s"].min(),
            "avg_degradation_seconds_per_lap": g["degradation_seconds_per_lap"].mean(),
        })
    return pd.DataFrame(rows)
