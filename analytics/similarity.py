"""Telemetry similarity between two laps, via a distance-aligned delta-time
trace -- the standard motorsport-engineering way to compare two laps (see
where one gained or lost time relative to the other along the track), not
something reasonably expressed as a SQL aggregate: it needs numerical
integration (speed -> distance) and interpolation onto a shared grid.

The stored schema has no raw distance channel (FastF1 doesn't provide one
directly either -- `add_distance()` in the FastF1 API itself is a derived
helper, not a source field), so distance is computed here from speed via
cumulative trapezoidal integration.

That integration is also this module's real limitation: two independently
speed-integrated distance axes can drift apart over a lap, especially for
a lap with an irregular pace (traffic, defending), enough that the
resulting delta trace can be numerically wrong by several seconds at a
given point even when the lap's overall time difference is precisely
known. This module doesn't try to fix that (it would need a real
distance/position reference this project's schema doesn't have);
analytics/service.py instead checks every delta's final value against the
exact lap_time difference it already has from the `laps` table and marks
the result unreliable when they disagree by more than a token amount,
rather than presenting a plausible-looking wrong number as trustworthy.
"""
import numpy as np
import pandas as pd


def _cumulative_trapezoid(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    dx = np.diff(x)
    avg_y = (y[1:] + y[:-1]) / 2
    return np.concatenate([[0.0], np.cumsum(avg_y * dx)])


def _distance_time(tel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Returns (cumulative_distance_m, session_time_s), sorted and with
    distance forced non-decreasing (telemetry noise/glitches could
    otherwise produce a tiny backwards step that breaks interpolation,
    which requires a monotonic x-axis)."""
    tel = tel.dropna(subset=["session_time", "speed"]).sort_values("session_time")
    t = tel["session_time"].apply(lambda td: td.total_seconds()).to_numpy()
    speed_ms = tel["speed"].to_numpy() / 3.6
    distance = _cumulative_trapezoid(speed_ms, t)
    distance = np.maximum.accumulate(distance)
    return distance, t


def compute_lap_telemetry_delta(tel_a: pd.DataFrame, tel_b: pd.DataFrame, n_points: int = 100) -> dict | None:
    """Positive delta at a given distance means lap B has taken longer to
    reach that point than lap A -- i.e. B is behind/slower there. Returns
    None if either lap has fewer than 2 usable telemetry samples (nothing
    to integrate)."""
    da, ta = _distance_time(tel_a)
    db, tb = _distance_time(tel_b)
    if len(da) < 2 or len(db) < 2:
        return None

    common_distance_m = min(da[-1], db[-1])
    if common_distance_m <= 0:
        return None

    grid = np.linspace(0, common_distance_m, n_points)
    time_a = np.interp(grid, da, ta - ta[0])
    time_b = np.interp(grid, db, tb - tb[0])
    delta = time_b - time_a

    max_gain_idx = int(np.argmin(delta))   # most negative = B's biggest relative gain
    max_loss_idx = int(np.argmax(delta))   # most positive = B's biggest relative loss

    return {
        "common_distance_m": float(common_distance_m),
        "final_delta_s": float(delta[-1]),
        "mean_abs_delta_s": float(np.mean(np.abs(delta))),
        "max_gain_s": float(delta[max_gain_idx]),
        "max_gain_at_distance_m": float(grid[max_gain_idx]),
        "max_loss_s": float(delta[max_loss_idx]),
        "max_loss_at_distance_m": float(grid[max_loss_idx]),
        "distance_grid_m": [round(v, 1) for v in grid.tolist()],
        "delta_trace_s": [round(v, 4) for v in delta.tolist()],
    }
