"""Pure transform logic: FastF1-shaped DataFrames -> rows matching supabase/schema.sql.

No I/O and no database connection here on purpose -- every function takes
and returns pandas objects, so unit tests can run these against pulled
fixtures without a live database.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SessionMeta:
    season: int
    round_number: int
    event_name: str
    event_slug: str
    location: str | None
    country: str | None
    event_format: str
    session_type: str          # must match supabase/schema.sql's sessions.session_type check
    session_name: str
    event_date: str            # ISO date, e.g. '2026-07-26'


@dataclass
class SessionSourceData:
    meta: SessionMeta
    laps: pd.DataFrame
    results: pd.DataFrame
    track_status: pd.DataFrame
    session_status: pd.DataFrame
    weather: pd.DataFrame
    race_control_messages: pd.DataFrame
    car_telemetry: pd.DataFrame        # combined across drivers, has DriverNumber column
    position_telemetry: pd.DataFrame   # combined across drivers, has DriverNumber column


@dataclass
class TransformedSession:
    meta: SessionMeta
    teams: pd.DataFrame
    drivers: pd.DataFrame
    session_results: pd.DataFrame
    track_status_events: pd.DataFrame
    session_status_events: pd.DataFrame
    weather_samples: pd.DataFrame
    race_control_messages: pd.DataFrame
    setup_revisions: pd.DataFrame       # driver_number, stint_number, compound, tyre_life_start, fresh_tyre
    stints: pd.DataFrame                # driver_number, stint_number, lap_start, lap_end
    laps: pd.DataFrame                  # driver_id, driver_number, lap_number, stint_number, ...
    car_telemetry_samples: pd.DataFrame     # driver_id, driver_number, lap_number (nullable), ...
    position_telemetry_samples: pd.DataFrame


RCM_DETAIL_COLUMNS = ["Status", "Flag", "Scope", "Sector", "RacingNumber", "Lap"]


def _normalize_color(color) -> str | None:
    if not isinstance(color, str) or not color:
        return None
    return color if color.startswith("#") else f"#{color}"


def build_teams(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame(columns=["id", "name", "color"])
    teams = (
        results[["TeamId", "TeamName", "TeamColor"]]
        .dropna(subset=["TeamId"])
        .drop_duplicates(subset=["TeamId"])
        .rename(columns={"TeamId": "id", "TeamName": "name", "TeamColor": "color"})
    )
    teams["color"] = teams["color"].apply(_normalize_color)
    return teams.reset_index(drop=True)


def build_drivers(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame(
            columns=["id", "full_name", "abbreviation", "broadcast_name", "country_code", "headshot_url"]
        )
    drivers = (
        results[["DriverId", "FullName", "Abbreviation", "BroadcastName", "CountryCode", "HeadshotUrl"]]
        .dropna(subset=["DriverId"])
        .drop_duplicates(subset=["DriverId"])
        .rename(
            columns={
                "DriverId": "id",
                "FullName": "full_name",
                "Abbreviation": "abbreviation",
                "BroadcastName": "broadcast_name",
                "CountryCode": "country_code",
                "HeadshotUrl": "headshot_url",
            }
        )
    )
    return drivers.reset_index(drop=True)


def driver_number_to_id_map(results: pd.DataFrame) -> dict[str, str]:
    if results.empty:
        return {}
    return dict(zip(results["DriverNumber"].astype(str), results["DriverId"], strict=True))


def build_session_results(results: pd.DataFrame, driver_map: dict[str, str]) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame(
            columns=[
                "driver_id", "team_id", "driver_number", "position", "classified_position",
                "grid_position", "q1", "q2", "q3", "finish_time", "status", "points", "laps_completed",
            ]
        )
    out = pd.DataFrame({
        "driver_id": results["DriverNumber"].astype(str).map(driver_map),
        "team_id": results["TeamId"],
        "driver_number": results["DriverNumber"].astype(int),
        "position": results["Position"],
        "classified_position": results["ClassifiedPosition"].astype(str),
        "grid_position": results["GridPosition"],
        "q1": results["Q1"],
        "q2": results["Q2"],
        "q3": results["Q3"],
        "finish_time": results["Time"],
        "status": results["Status"],
        "points": results["Points"],
        "laps_completed": results["Laps"],
    })
    return out


def build_track_status_events(track_status: pd.DataFrame) -> pd.DataFrame:
    if track_status.empty:
        return pd.DataFrame(columns=["occurred_at", "status_code", "message"])
    return pd.DataFrame({
        "occurred_at": track_status["Time"],
        "status_code": track_status["Status"].astype(str),
        "message": track_status["Message"],
    })


def build_session_status_events(session_status: pd.DataFrame) -> pd.DataFrame:
    if session_status.empty:
        return pd.DataFrame(columns=["occurred_at", "status"])
    return pd.DataFrame({
        "occurred_at": session_status["Time"],
        "status": session_status["Status"],
    })


def build_weather_samples(weather: pd.DataFrame) -> pd.DataFrame:
    if weather.empty:
        return pd.DataFrame(columns=[
            "occurred_at", "air_temp", "humidity", "pressure", "rainfall", "track_temp",
            "wind_direction", "wind_speed",
        ])
    return pd.DataFrame({
        "occurred_at": weather["Time"],
        "air_temp": weather["AirTemp"],
        "humidity": weather["Humidity"],
        "pressure": weather["Pressure"],
        "rainfall": weather["Rainfall"].astype(bool),
        "track_temp": weather["TrackTemp"],
        "wind_direction": weather["WindDirection"],
        "wind_speed": weather["WindSpeed"],
    })


def build_race_control_messages(rcm: pd.DataFrame) -> pd.DataFrame:
    if rcm.empty:
        return pd.DataFrame(columns=["occurred_at", "category", "message", "details"])

    def _details(row) -> dict:
        d = {}
        for col in RCM_DETAIL_COLUMNS:
            val = row.get(col)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                continue
            d[col.lower()] = val
        return d

    return pd.DataFrame({
        "occurred_at": rcm["Time"],
        "category": rcm["Category"],
        "message": rcm["Message"],
        "details": [_details(row) for _, row in rcm.iterrows()],
    })


def build_setup_revisions_and_stints(laps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group laps by (DriverNumber, Stint) -- each group is one stint on one
    tyre configuration. FastF1 doesn't expose anything else about car setup,
    so setup_revisions is scoped to tyre config only (see schema.sql)."""
    if laps.empty:
        empty_setup = pd.DataFrame(columns=["driver_number", "stint_number", "compound", "tyre_life_start", "fresh_tyre"])
        empty_stints = pd.DataFrame(columns=["driver_number", "stint_number", "lap_start", "lap_end"])
        return empty_setup, empty_stints

    grouped = laps.dropna(subset=["Stint"]).sort_values(["DriverNumber", "Stint", "LapNumber"])
    setup_rows = []
    stint_rows = []
    for (drv, stint_num), g in grouped.groupby(["DriverNumber", "Stint"], sort=False):
        first = g.iloc[0]
        setup_rows.append({
            "driver_number": drv,
            "stint_number": int(stint_num),
            "compound": first["Compound"],
            "tyre_life_start": first["TyreLife"],
            "fresh_tyre": bool(first["FreshTyre"]) if pd.notna(first["FreshTyre"]) else False,
        })
        stint_rows.append({
            "driver_number": drv,
            "stint_number": int(stint_num),
            "lap_start": int(g["LapNumber"].min()),
            "lap_end": int(g["LapNumber"].max()),
        })
    return pd.DataFrame(setup_rows), pd.DataFrame(stint_rows)


def build_laps(laps: pd.DataFrame, driver_map: dict[str, str]) -> pd.DataFrame:
    if laps.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "driver_id": laps["DriverNumber"].astype(str).map(driver_map),
        "driver_number": laps["DriverNumber"].astype(str),
        "stint_number": laps["Stint"],
        "lap_number": laps["LapNumber"].astype(int),
        "lap_time": laps["LapTime"],
        "lap_start_time": laps["LapStartTime"],
        "lap_start_date": laps["LapStartDate"],
        "sector1_time": laps["Sector1Time"],
        "sector2_time": laps["Sector2Time"],
        "sector3_time": laps["Sector3Time"],
        "sector1_session_time": laps["Sector1SessionTime"],
        "sector2_session_time": laps["Sector2SessionTime"],
        "sector3_session_time": laps["Sector3SessionTime"],
        "speed_i1": laps["SpeedI1"],
        "speed_i2": laps["SpeedI2"],
        "speed_fl": laps["SpeedFL"],
        "speed_st": laps["SpeedST"],
        "is_personal_best": laps["IsPersonalBest"].astype(bool),
        "compound": laps["Compound"],
        "tyre_life": laps["TyreLife"],
        "fresh_tyre": laps["FreshTyre"],
        "track_status": laps["TrackStatus"].astype(str),
        "position": laps["Position"],
        "pit_in_time": laps["PitInTime"],
        "pit_out_time": laps["PitOutTime"],
        "deleted": laps["Deleted"].astype(bool),
        "deleted_reason": laps["DeletedReason"].replace("", None),
        "is_accurate": laps["IsAccurate"].astype(bool),
        "fastf1_generated": laps["FastF1Generated"].astype(bool),
    })
    return out


def _assign_lap_numbers(sample_times: pd.Series, lap_starts: np.ndarray, lap_numbers: np.ndarray) -> np.ndarray:
    """For each sample's session-relative time, find which lap it falls in
    (lap_starts must be sorted ascending). Samples before the first known lap
    start get NaN -- left null rather than guessed, per schema.sql's comment
    that lap_id is only populated when unambiguous."""
    idx = np.searchsorted(lap_starts, sample_times.values, side="right") - 1
    result = np.where(idx >= 0, lap_numbers[np.clip(idx, 0, len(lap_numbers) - 1)], np.nan)
    return result


def _build_telemetry(telemetry: pd.DataFrame, driver_map: dict[str, str], laps_by_driver: pd.DataFrame,
                      extra_cols: dict[str, str]) -> pd.DataFrame:
    if telemetry.empty:
        return pd.DataFrame()

    telemetry = telemetry.copy()
    telemetry["driver_number"] = telemetry["DriverNumber"].astype(str)
    telemetry["driver_id"] = telemetry["driver_number"].map(driver_map)

    lap_number_parts = []
    for drv, grp in telemetry.groupby("driver_number", sort=False):
        driver_laps = laps_by_driver[laps_by_driver["driver_number"] == drv].sort_values("lap_start_time")
        if driver_laps.empty:
            lap_numbers = np.full(len(grp), np.nan)
        else:
            lap_starts = driver_laps["lap_start_time"].dt.total_seconds().values
            lap_nums = driver_laps["lap_number"].values
            sample_secs = grp["SessionTime"].dt.total_seconds()
            lap_numbers = _assign_lap_numbers(sample_secs, lap_starts, lap_nums)
        lap_number_parts.append(pd.Series(lap_numbers, index=grp.index))
    telemetry["lap_number"] = pd.concat(lap_number_parts).sort_index()

    cols = {
        "driver_id": telemetry["driver_id"],
        "driver_number": telemetry["driver_number"],
        "lap_number": telemetry["lap_number"],
        "captured_at": telemetry["Date"],
        "session_time": telemetry["SessionTime"],
        "source": telemetry["Source"],
    }
    for db_col, src_col in extra_cols.items():
        cols[db_col] = telemetry[src_col]
    return pd.DataFrame(cols)


def build_car_telemetry_samples(car_telemetry: pd.DataFrame, driver_map: dict[str, str],
                                 laps_out: pd.DataFrame) -> pd.DataFrame:
    return _build_telemetry(car_telemetry, driver_map, laps_out, {
        "rpm": "RPM", "speed": "Speed", "n_gear": "nGear", "throttle": "Throttle",
        "brake": "Brake", "drs": "DRS",
    })


def build_position_telemetry_samples(position_telemetry: pd.DataFrame, driver_map: dict[str, str],
                                      laps_out: pd.DataFrame) -> pd.DataFrame:
    return _build_telemetry(position_telemetry, driver_map, laps_out, {
        "status": "Status", "x": "X", "y": "Y", "z": "Z",
    })


def _normalize_none_compound(laps: pd.DataFrame) -> pd.DataFrame:
    """FastF1 encodes an unavailable compound as the literal string 'None'
    (seen on real stints where its own tyre tracking breaks mid-session),
    not an actual null -- left as-is, that string would silently become
    its own bogus category in any GROUP BY compound downstream."""
    if laps.empty or "Compound" not in laps.columns:
        return laps
    laps = laps.copy()
    laps["Compound"] = laps["Compound"].replace("None", None)
    return laps


def _is_unresolved(driver_id_col: pd.Series) -> pd.Series:
    return driver_id_col.astype(str).isin(["nan", ""])


def _resolve_driver_ids(results: pd.DataFrame,
                         driver_number_fallback: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """FastF1 leaves DriverId/TeamId unresolved in two different ways: the
    literal string 'nan' (not a real null, so .dropna() misses it) for
    individual entrants with no classified position, or a blank string for
    every driver at once on session types Ergast doesn't support -- seen on
    Sprint Qualifying ("Limited results are calculated from timing data").
    TeamName/TeamColor/Abbreviation/FullName stay populated even then, so
    in the whole-session case a driver's own already-known identity (from
    another session, via driver_number_fallback) recovers real results
    instead of losing the session entirely. Whatever's still unresolved
    after that -- true one-off unclassified entrants, or an unraced driver
    number with no prior session to borrow from -- gets dropped: every one
    of these in a session would otherwise share the same blank id, which
    collides on session_results' unique (session_id, driver_id) constraint,
    and dropping them loses nothing meaningful since they have no
    classified result either way. laps_source is filtered to match in
    transform_session, so no downstream table (laps, stints,
    setup_revisions, telemetry) is left trying to reference a driver that
    was just excluded from `drivers`."""
    if results.empty or "DriverId" not in results.columns:
        return results
    results = results.copy()
    unresolved = _is_unresolved(results["DriverId"])
    if driver_number_fallback and unresolved.any():
        for idx in results.index[unresolved]:
            fallback = driver_number_fallback.get(str(results.at[idx, "DriverNumber"]))
            if fallback:
                results.at[idx, "DriverId"], results.at[idx, "TeamId"] = fallback
        unresolved = _is_unresolved(results["DriverId"])
    return results[~unresolved].reset_index(drop=True)


def _drop_unmapped(df: pd.DataFrame, driver_map: dict[str, str]) -> pd.DataFrame:
    if df.empty or "DriverNumber" not in df.columns:
        return df
    return df[df["DriverNumber"].astype(str).isin(driver_map)].reset_index(drop=True)


def transform_session(data: SessionSourceData,
                       driver_number_fallback: dict[str, tuple[str, str]] | None = None) -> TransformedSession:
    results = _resolve_driver_ids(data.results, driver_number_fallback)
    driver_map = driver_number_to_id_map(results)
    # Every driver_map-keyed table (laps, stints, setup_revisions, both
    # telemetry tables) has a not-null driver_id FK into `drivers` --
    # feeding any of them a DriverNumber that _drop_unresolved_drivers just
    # excluded from `drivers` would crash the insert, so they all get the
    # same filter applied to their source before the resolve step below.
    laps_source = _drop_unmapped(_normalize_none_compound(data.laps), driver_map)
    car_telemetry = _drop_unmapped(data.car_telemetry, driver_map)
    position_telemetry = _drop_unmapped(data.position_telemetry, driver_map)

    laps_out = build_laps(laps_source, driver_map)
    setup_revisions, stints = build_setup_revisions_and_stints(laps_source)

    return TransformedSession(
        meta=data.meta,
        teams=build_teams(results),
        drivers=build_drivers(results),
        session_results=build_session_results(results, driver_map),
        track_status_events=build_track_status_events(data.track_status),
        session_status_events=build_session_status_events(data.session_status),
        weather_samples=build_weather_samples(data.weather),
        race_control_messages=build_race_control_messages(data.race_control_messages),
        setup_revisions=setup_revisions,
        stints=stints,
        laps=laps_out,
        car_telemetry_samples=build_car_telemetry_samples(car_telemetry, driver_map, laps_out),
        position_telemetry_samples=build_position_telemetry_samples(position_telemetry, driver_map, laps_out),
    )
