"""Idempotent writer: TransformedSession -> Postgres, via supabase/schema.sql's tables.

Idempotency strategy: a session is identified by its natural key (season,
round_number, session_type). Re-ingesting a weekend upserts that one
`sessions` row (same id back), then deletes every child row for that
session_id and re-inserts the freshly transformed rows, all inside one
transaction. That means a second run for the same weekend produces exactly
the same row set instead of appending duplicates, and a failure partway
through leaves the previous ingested state untouched rather than a half
re-written weekend.

teams/drivers are the exception: they're global reference data shared across
sessions, so they're upserted (ON CONFLICT ... DO UPDATE) rather than
deleted, keyed on FastF1's own stable ids.
"""
import os

import pandas as pd
import psycopg2
import psycopg2.extras

from ingest.transform import TransformedSession

# Deletes must run children-before-parents to respect the FKs declared in
# schema.sql (car/position telemetry and laps reference stints/laps, which
# aren't cascade-deleted from sessions the way the other child tables are --
# see schema.sql's `on delete cascade` placement).
_DELETE_ORDER = [
    "car_telemetry_samples",
    "position_telemetry_samples",
    "laps",
    "stints",
    "setup_revisions",
    "session_results",
    "track_status_events",
    "session_status_events",
    "weather_samples",
    "race_control_messages",
]


def get_connection():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set -- see .env.example")
    return psycopg2.connect(dsn)


def _upsert_teams(cur, teams) -> None:
    if teams.empty:
        return
    rows = list(teams[["id", "name", "color"]].itertuples(index=False, name=None))
    psycopg2.extras.execute_values(
        cur,
        """
        insert into public.teams (id, name, color) values %s
        on conflict (id) do update set name = excluded.name, color = excluded.color
        """,
        rows,
    )


def _upsert_drivers(cur, drivers) -> None:
    if drivers.empty:
        return
    cols = ["id", "full_name", "abbreviation", "broadcast_name", "country_code", "headshot_url"]
    rows = list(drivers[cols].itertuples(index=False, name=None))
    psycopg2.extras.execute_values(
        cur,
        """
        insert into public.drivers (id, full_name, abbreviation, broadcast_name, country_code, headshot_url)
        values %s
        on conflict (id) do update set
          full_name = excluded.full_name,
          abbreviation = excluded.abbreviation,
          broadcast_name = excluded.broadcast_name,
          country_code = excluded.country_code,
          headshot_url = excluded.headshot_url
        """,
        rows,
    )


def _upsert_session(cur, meta, owner_user_id: str) -> int:
    cur.execute(
        """
        insert into public.sessions
          (user_id, season, round_number, event_name, event_slug, location, country,
           event_format, session_type, session_name, event_date)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (season, round_number, session_type) do update set
          event_name = excluded.event_name,
          event_slug = excluded.event_slug,
          location = excluded.location,
          country = excluded.country,
          event_format = excluded.event_format,
          session_name = excluded.session_name,
          event_date = excluded.event_date
        returning id
        """,
        (
            owner_user_id, meta.season, meta.round_number, meta.event_name, meta.event_slug,
            meta.location, meta.country, meta.event_format, meta.session_type, meta.session_name,
            meta.event_date,
        ),
    )
    return cur.fetchone()[0]


def _delete_children(cur, session_id: int) -> None:
    for table in _DELETE_ORDER:
        cur.execute(f"delete from public.{table} where session_id = %s", (session_id,))


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """pandas' NaN/NaT don't adapt to SQL NULL through psycopg2 -- they get
    stringified ("NaT") and blow up as invalid literals. Every DataFrame
    must pass through this before itertuples() feeds a query."""
    return df.astype(object).where(pd.notna(df), None)


def _bulk_insert(cur, table: str, df, session_id: int, columns: list[str],
                  returning: list[str] | None = None):
    if df.empty:
        return []
    values = [(session_id, *row) for row in _clean(df[columns]).itertuples(index=False, name=None)]
    col_list = ", ".join(["session_id"] + columns)
    sql = f"insert into public.{table} ({col_list}) values %s"
    if returning:
        sql += f" returning {', '.join(returning)}"
        return psycopg2.extras.execute_values(cur, sql, values, fetch=True, page_size=5000)
    psycopg2.extras.execute_values(cur, sql, values, page_size=5000)
    return []


def write_session(conn, t: TransformedSession, owner_user_id: str, telemetry_driver_ids=None) -> int:
    """telemetry_driver_ids, when given, restricts car/position telemetry
    writes to that set of driver_ids -- everyone still gets laps/results/
    stints/setup_revisions, just not the two high-volume telemetry tables.
    None (the default) preserves the original unfiltered behavior exactly,
    used by every single-weekend ingest_weekend.py call. See
    ingest/tiering.py for how the set gets decided."""
    with conn:
        with conn.cursor() as cur:
            _upsert_teams(cur, t.teams)
            _upsert_drivers(cur, t.drivers)
            session_id = _upsert_session(cur, t.meta, owner_user_id)
            _delete_children(cur, session_id)

            _bulk_insert(cur, "session_results", t.session_results, session_id, [
                "driver_id", "team_id", "driver_number", "position", "classified_position",
                "grid_position", "q1", "q2", "q3", "finish_time", "status", "points", "laps_completed",
            ])
            _bulk_insert(cur, "track_status_events", t.track_status_events, session_id, [
                "occurred_at", "status_code", "message",
            ])
            _bulk_insert(cur, "session_status_events", t.session_status_events, session_id, [
                "occurred_at", "status",
            ])
            _bulk_insert(cur, "weather_samples", t.weather_samples, session_id, [
                "occurred_at", "air_temp", "humidity", "pressure", "rainfall", "track_temp",
                "wind_direction", "wind_speed",
            ])
            if not t.race_control_messages.empty:
                rcm = t.race_control_messages.copy()
                rcm["details"] = rcm["details"].apply(psycopg2.extras.Json)
                _bulk_insert(cur, "race_control_messages", rcm, session_id, [
                    "occurred_at", "category", "message", "details",
                ])

            # driver_number -> driver_id: laps already carries both, computed
            # once in transform.py -- reuse it instead of re-deriving here.
            driver_id_by_number: dict[str, str] = {}
            if not t.laps.empty:
                driver_id_by_number = dict(
                    zip(t.laps["driver_number"], t.laps["driver_id"], strict=True)
                )

            # setup_revisions has no natural unique key, so each row is
            # inserted individually and its (driver_number, stint_number) ->
            # id mapping is taken straight from the loop variables --
            # unambiguous by construction, unlike correlating a bulk
            # RETURNING batch back to input rows after the fact would be.
            setup_revision_ids: dict[tuple[str, int], int] = {}
            for row in _clean(t.setup_revisions).itertuples(index=False):
                driver_id = driver_id_by_number.get(row.driver_number)
                cur.execute(
                    """
                    insert into public.setup_revisions
                      (session_id, driver_id, compound, tyre_life_start, fresh_tyre)
                    values (%s, %s, %s, %s, %s)
                    returning id
                    """,
                    (session_id, driver_id, row.compound, row.tyre_life_start, row.fresh_tyre),
                )
                setup_revision_ids[(row.driver_number, row.stint_number)] = cur.fetchone()[0]

            # stints: (driver_id, stint_number) is unique within a session by
            # schema.sql's own constraint, so it's safe to correlate a bulk
            # RETURNING batch back to rows by that pair.
            stint_ids: dict[tuple[str, int], int] = {}
            if not t.stints.empty:
                stint_rows = []
                for row in _clean(t.stints).itertuples(index=False):
                    driver_id = driver_id_by_number.get(row.driver_number)
                    setup_revision_id = setup_revision_ids.get((row.driver_number, row.stint_number))
                    stint_rows.append((
                        session_id, driver_id, row.stint_number, setup_revision_id,
                        row.lap_start, row.lap_end,
                    ))
                returned = psycopg2.extras.execute_values(
                    cur,
                    """
                    insert into public.stints
                      (session_id, driver_id, stint_number, setup_revision_id, lap_start, lap_end)
                    values %s
                    returning id, driver_id, stint_number
                    """,
                    stint_rows,
                    fetch=True,
                )
                for stint_id, driver_id, stint_number in returned:
                    stint_ids[(driver_id, stint_number)] = stint_id

            # laps: (driver_id, lap_number) is unique within a session by
            # schema.sql's constraint, same safe correlation as stints.
            lap_ids: dict[tuple[str, int], int] = {}
            if not t.laps.empty:
                laps_df = t.laps.copy()
                laps_df["stint_id"] = laps_df.apply(
                    lambda r: stint_ids.get((r["driver_id"], r["stint_number"])) if pd.notna(r["stint_number"]) else None,
                    axis=1,
                )
                cols = [
                    "driver_id", "stint_id", "lap_number", "lap_time", "lap_start_time", "lap_start_date",
                    "sector1_time", "sector2_time", "sector3_time", "sector1_session_time",
                    "sector2_session_time", "sector3_session_time", "speed_i1", "speed_i2", "speed_fl",
                    "speed_st", "is_personal_best", "compound", "tyre_life", "fresh_tyre", "track_status",
                    "position", "pit_in_time", "pit_out_time", "deleted", "deleted_reason", "is_accurate",
                    "fastf1_generated",
                ]
                values = [(session_id, *row) for row in _clean(laps_df[cols]).itertuples(index=False, name=None)]
                returned = psycopg2.extras.execute_values(
                    cur,
                    f"insert into public.laps (session_id, {', '.join(cols)}) values %s "
                    "returning id, driver_id, lap_number",
                    values,
                    fetch=True,
                    page_size=5000,
                )
                for lap_id, driver_id, lap_number in returned:
                    lap_ids[(driver_id, lap_number)] = lap_id

            for table, df, extra_cols in (
                ("car_telemetry_samples", t.car_telemetry_samples,
                 ["rpm", "speed", "n_gear", "throttle", "brake", "drs"]),
                ("position_telemetry_samples", t.position_telemetry_samples,
                 ["status", "x", "y", "z"]),
            ):
                if df.empty:
                    continue
                tel = df.copy()
                if telemetry_driver_ids is not None:
                    tel = tel[tel["driver_id"].isin(telemetry_driver_ids)]
                    if tel.empty:
                        continue
                tel["lap_id"] = [
                    lap_ids.get((driver_id, lap_number)) if pd.notna(lap_number) else None
                    for driver_id, lap_number in zip(tel["driver_id"], tel["lap_number"], strict=True)
                ]
                cols = ["driver_id", "lap_id", "captured_at", "session_time"] + extra_cols + ["source"]
                values = [(session_id, *row) for row in _clean(tel[cols]).itertuples(index=False, name=None)]
                psycopg2.extras.execute_values(
                    cur,
                    f"insert into public.{table} (session_id, {', '.join(cols)}) values %s",
                    values,
                    page_size=5000,
                )
    return session_id

