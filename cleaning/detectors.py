"""Pure detector functions: TransformedSession's constituent DataFrames ->
data-quality findings. No I/O, no database connection, so tests can run
these against deliberately malformed fixtures without a live database.

Every detector returns rows that get persisted (via cleaning/db.py) rather
than silently dropping or masking bad data -- nothing here mutates or
removes a row from `laps`/telemetry; it only annotates.
"""
import pandas as pd

# FastF1's own track status codes. '3' never appears in practice but is
# included per FastF1's documented vocabulary for completeness.
TRACK_STATUS_LABELS = {
    "2": "yellow",
    "3": "yellow",       # double yellow
    "4": "safety_car",
    "5": "red_flag",
    "6": "vsc",
    "7": "vsc_ending",
}

# Real session lifecycles frequently pass through 'Aborted' mid-session (a
# red flag that resumes later in the same session -- e.g. Q1 red-flagged
# then restarted) and still reach 'Ends' normally. Only a session whose
# status timeline never reaches this terminal state is actually incomplete.
TERMINAL_STATUS = "Ends"


def derive_caution_periods(track_status_events: pd.DataFrame) -> pd.DataFrame:
    """Pair track status transitions into caution periods. A period opens on
    the first non-AllClear ('1') event and closes on the next '1'; a run of
    different non-'1' codes without an intervening '1' (e.g. yellow ->
    safety car for the same incident) stays one period, labeled by the code
    that opened it. A period never closed before the data ends gets
    end_time=None rather than a guessed value."""
    cols = ["period_type", "start_time", "end_time"]
    if track_status_events.empty:
        return pd.DataFrame(columns=cols)

    events = track_status_events.sort_values("occurred_at")
    periods = []
    open_period = None
    for _, ev in events.iterrows():
        code = str(ev["status_code"])
        if code == "1":
            if open_period is not None:
                open_period["end_time"] = ev["occurred_at"]
                periods.append(open_period)
                open_period = None
        elif open_period is None:
            open_period = {
                "period_type": TRACK_STATUS_LABELS.get(code, f"code_{code}"),
                "start_time": ev["occurred_at"],
                "end_time": None,
            }
        # else: already inside a period -- code changed without an
        # intervening AllClear, treat as the same ongoing incident.
    if open_period is not None:
        periods.append(open_period)
    return pd.DataFrame(periods, columns=cols)


def _lap_overlaps_period(lap_start, lap_end, period_start, period_end) -> bool:
    if pd.isna(lap_start) or pd.isna(lap_end):
        return False
    if period_end is None:
        return lap_end >= period_start
    return lap_start < period_end and lap_end > period_start


def detect_caution_period_laps(laps: pd.DataFrame, caution_periods: pd.DataFrame) -> pd.DataFrame:
    """Flag laps whose time window overlaps a caution period -- these are
    real laps (not deleted, not necessarily slow) but not representative of
    green-flag pace, so degradation/pace modeling should be able to exclude
    them without losing the underlying data."""
    cols = ["driver_id", "lap_number", "category", "reason"]
    if laps.empty or caution_periods.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    laps = laps.dropna(subset=["lap_start_time", "lap_time"])
    lap_end = laps["lap_start_time"] + laps["lap_time"]
    for (driver_id, lap_number, start, end) in zip(
        laps["driver_id"], laps["lap_number"], laps["lap_start_time"], lap_end, strict=True
    ):
        for _, period in caution_periods.iterrows():
            if _lap_overlaps_period(start, end, period["start_time"], period["end_time"]):
                rows.append({
                    "driver_id": driver_id,
                    "lap_number": lap_number,
                    "category": "caution_period",
                    "reason": f"overlaps {period['period_type']} period starting at {period['start_time']}",
                })
                break
    return pd.DataFrame(rows, columns=cols)


def detect_steward_and_confidence_exclusions(laps: pd.DataFrame) -> pd.DataFrame:
    """Re-surface FastF1's own per-lap flags (deleted, in/out laps, low
    timing confidence) as lap_exclusions rows -- these already live as
    columns on `laps` (schema.sql), but pulling them into the same unified
    table as every other exclusion category means downstream views only
    ever need to query lap_exclusions, not remember five different columns."""
    cols = ["driver_id", "lap_number", "category", "reason"]
    if laps.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for _, lap in laps.iterrows():
        if lap.get("deleted"):
            reason = lap.get("deleted_reason") or "deleted (no reason recorded)"
            rows.append({"driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                         "category": "steward_deleted", "reason": reason})
        if pd.notna(lap.get("pit_in_time")):
            rows.append({"driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                         "category": "pit_lap", "reason": "in-lap (ends with pit entry)"})
        if pd.notna(lap.get("pit_out_time")):
            rows.append({"driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                         "category": "pit_lap", "reason": "out-lap (starts with pit exit)"})
        if lap.get("is_accurate") is False:
            rows.append({"driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                         "category": "low_confidence", "reason": "FastF1 IsAccurate=False"})
    return pd.DataFrame(rows, columns=cols)


def detect_timing_anomalies(laps: pd.DataFrame, implausible_pace_ratio: float = 0.5,
                             sector_sum_tolerance_s: float = 1.0) -> pd.DataFrame:
    """Two independent checks, neither of which needs external reference
    data: (1) a lap time far faster than the session's typical pace is a
    timing glitch, not a real lap -- compared against the session's *median*
    lap time rather than its minimum, since a single already-anomalous lap
    would otherwise corrupt its own reference point (the min would just be
    the anomaly itself); (2) sector times that don't sum close to the
    recorded lap time indicate inconsistent/corrupted timing data for that
    lap, regardless of whether the lap time itself looks plausible alone."""
    cols = ["driver_id", "lap_number", "category", "reason"]
    if laps.empty:
        return pd.DataFrame(columns=cols)

    valid_times = laps["lap_time"].dropna()
    median = valid_times.median() if not valid_times.empty else None

    rows = []
    for _, lap in laps.iterrows():
        lt = lap.get("lap_time")
        if pd.isna(lt):
            continue
        lt_s = lt.total_seconds()

        if median is not None and lt_s < median.total_seconds() * implausible_pace_ratio:
            rows.append({
                "driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                "category": "timing_anomaly",
                "reason": (f"lap time {lt_s:.3f}s is under {implausible_pace_ratio:.0%} of the "
                           f"session's median lap time ({median.total_seconds():.3f}s) -- implausible pace"),
            })

        sectors = [lap.get("sector1_time"), lap.get("sector2_time"), lap.get("sector3_time")]
        if all(pd.notna(s) for s in sectors):
            total_s = sum(s.total_seconds() for s in sectors)
            if abs(total_s - lt_s) > sector_sum_tolerance_s:
                rows.append({
                    "driver_id": lap["driver_id"], "lap_number": lap["lap_number"],
                    "category": "timing_anomaly",
                    "reason": f"sector times sum to {total_s:.3f}s but lap_time is {lt_s:.3f}s",
                })
    return pd.DataFrame(rows, columns=cols)


def build_lap_exclusions(laps: pd.DataFrame, caution_periods: pd.DataFrame) -> pd.DataFrame:
    """Union of every lap-level exclusion detector. A lap can appear more
    than once (e.g. both steward_deleted and timing_anomaly) -- that's
    intentional, each row documents one independent reason."""
    frames = [
        detect_steward_and_confidence_exclusions(laps),
        detect_caution_period_laps(laps, caution_periods),
        detect_timing_anomalies(laps),
    ]
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame(columns=["driver_id", "lap_number", "category", "reason"])
    return pd.concat(non_empty, ignore_index=True)


def detect_incomplete_session(session_status_events: pd.DataFrame) -> pd.DataFrame:
    """A session is incomplete only if its status timeline never reaches the
    terminal 'Ends' state -- 'Aborted' by itself is a routine red-flag/
    restart within a session, not a failure. Also surfaces red-flag
    interruption counts as a lower-severity, non-blocking flag --
    informational, not "incomplete"."""
    cols = ["driver_id", "issue_type", "detail"]
    if session_status_events.empty:
        return pd.DataFrame([{"driver_id": None, "issue_type": "incomplete_session",
                               "detail": "no session_status data recorded"}], columns=cols)

    ordered = session_status_events.sort_values("occurred_at")
    rows = []
    if ordered.iloc[-1]["status"] != TERMINAL_STATUS:
        rows.append({"driver_id": None, "issue_type": "incomplete_session",
                     "detail": f"session status timeline ends on '{ordered.iloc[-1]['status']}', "
                               f"never reached '{TERMINAL_STATUS}'"})
    red_flags = int((ordered["status"] == "Aborted").sum())
    if red_flags:
        rows.append({"driver_id": None, "issue_type": "red_flag_interruption",
                     "detail": f"session was red-flagged/aborted {red_flags} time(s) during its lifecycle"})
    return pd.DataFrame(rows, columns=cols)


def detect_missing_telemetry(session_results: pd.DataFrame, car_telemetry: pd.DataFrame,
                              position_telemetry: pd.DataFrame,
                              car_channels: tuple = ("rpm", "speed", "n_gear", "throttle", "brake", "drs"),
                              position_channels: tuple = ("x", "y", "z")) -> pd.DataFrame:
    """Per-driver telemetry completeness: flags a driver with zero telemetry
    rows for the session, and separately flags any channel that's entirely
    null across all of that driver's samples -- distinguishing "no data
    logged at all" (a session-level pull problem) from "logged, but this one
    channel is dead" (a car/sensor problem worth knowing about specifically)."""
    cols = ["driver_id", "issue_type", "detail"]
    if session_results.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for driver_id in session_results["driver_id"].dropna().unique():
        car = car_telemetry[car_telemetry["driver_id"] == driver_id] if not car_telemetry.empty else car_telemetry
        pos = position_telemetry[position_telemetry["driver_id"] == driver_id] if not position_telemetry.empty else position_telemetry

        if car.empty:
            rows.append({"driver_id": driver_id, "issue_type": "missing_car_telemetry",
                         "detail": "no car telemetry samples for this driver in this session"})
        else:
            for ch in car_channels:
                if ch in car.columns and car[ch].notna().sum() == 0:
                    rows.append({"driver_id": driver_id, "issue_type": "missing_channel",
                                 "detail": f"car telemetry channel '{ch}' is entirely null for this driver"})

        if pos.empty:
            rows.append({"driver_id": driver_id, "issue_type": "missing_position_telemetry",
                         "detail": "no position telemetry samples for this driver in this session"})
        else:
            for ch in position_channels:
                if ch in pos.columns and pos[ch].notna().sum() == 0:
                    rows.append({"driver_id": driver_id, "issue_type": "missing_channel",
                                 "detail": f"position telemetry channel '{ch}' is entirely null for this driver"})
    return pd.DataFrame(rows, columns=cols)


def build_session_quality_flags(session_status_events: pd.DataFrame, session_results: pd.DataFrame,
                                 car_telemetry: pd.DataFrame, position_telemetry: pd.DataFrame) -> pd.DataFrame:
    """Union of every session/driver-level (non-lap) quality detector."""
    frames = [
        detect_incomplete_session(session_status_events),
        detect_missing_telemetry(session_results, car_telemetry, position_telemetry),
    ]
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame(columns=["driver_id", "issue_type", "detail"])
    return pd.concat(non_empty, ignore_index=True)
