"""Telemetry-based lap anomaly detection -- distinct from the cleaning
pipeline (cleaning/detectors.py), which only looks at lap *times*
(sector-sum consistency, implausible pace). This looks at the telemetry
*shape* of a lap: unusual peak speed, throttle application, RPM, or an
unusually high number of brake on/off transitions relative to a driver's
own other laps -- the kind of thing that can flag a mechanical issue or a
scruffy lap even when the lap time itself looks unremarkable.

Restricted to laps the cleaning pipeline didn't already exclude (steward-
deleted, pit/in-out laps, caution-period laps): a slow min_speed on a pit
lane lap isn't an anomaly, it's normal, so mixing those in would just
re-flag things already explained under a different name.

Z-scores are computed against each driver's own lap population for the
session, not the whole field -- driving style varies enough driver to
driver that a shared baseline would mostly just measure who's naturally
smoother, not what's actually unusual for that driver.
"""
import pandas as pd


def _lap_telemetry_features(car_telemetry: pd.DataFrame) -> pd.DataFrame:
    tel = car_telemetry.dropna(subset=["lap_id"])
    rows = []
    for lap_id, g in tel.groupby("lap_id"):
        g = g.sort_values("session_time")
        brake = g["brake"]
        transitions = int((brake != brake.shift()).sum() - 1) if len(brake) > 1 else 0
        rows.append({
            "lap_id": lap_id,
            "max_speed": g["speed"].max(),
            "min_speed": g["speed"].min(),
            "avg_throttle": g["throttle"].mean(),
            "max_rpm": g["rpm"].max(),
            "brake_transitions": max(transitions, 0),
        })
    return pd.DataFrame(rows)


FEATURE_COLUMNS = ["max_speed", "min_speed", "avg_throttle", "max_rpm", "brake_transitions"]


def detect_lap_telemetry_anomalies(laps: pd.DataFrame, car_telemetry: pd.DataFrame,
                                    lap_exclusions: pd.DataFrame, z_threshold: float = 2.5,
                                    min_laps_for_baseline: int = 4) -> pd.DataFrame:
    """laps needs: id, driver_id, lap_number. car_telemetry needs: lap_id,
    speed, throttle, rpm, brake, session_time."""
    cols = ["driver_id", "lap_number", "feature", "value", "z_score", "driver_mean", "driver_std"]

    features = _lap_telemetry_features(car_telemetry)
    if features.empty:
        return pd.DataFrame(columns=cols)

    excluded_ids = set(lap_exclusions["lap_id"].unique()) if not lap_exclusions.empty else set()
    merged = laps[["id", "driver_id", "lap_number"]].merge(features, left_on="id", right_on="lap_id")
    merged = merged[~merged["id"].isin(excluded_ids)]

    rows = []
    for driver_id, g in merged.groupby("driver_id"):
        if len(g) < min_laps_for_baseline:
            continue
        for col in FEATURE_COLUMNS:
            vals = g[col].dropna()
            if len(vals) < min_laps_for_baseline:
                continue
            mean, std = vals.mean(), vals.std()
            if not std or pd.isna(std):
                continue
            z = (vals - mean) / std
            outlier_idx = z[z.abs() >= z_threshold].index
            for idx in outlier_idx:
                rows.append({
                    "driver_id": driver_id,
                    "lap_number": int(g.loc[idx, "lap_number"]),
                    "feature": col,
                    "value": float(g.loc[idx, col]),
                    "z_score": float(z.loc[idx]),
                    "driver_mean": float(mean),
                    "driver_std": float(std),
                })
    return pd.DataFrame(rows, columns=cols)
