"""Writer for cleaning/detectors.py's output: caution_periods, lap_exclusions,
session_quality_flags. Same idempotency strategy as ingest/db.py: delete this
session's rows in these three tables, then insert the freshly computed ones,
all in one transaction -- re-running cleaning for a weekend replaces its
findings rather than accumulating duplicates.

Runs against a session that's already been ingested -- lap_id isn't known
until laps exist in Postgres, so lap_exclusions' (driver_id, lap_number)
pairs are resolved against the real table here rather than carried
through from the transform step.
"""
import psycopg2.extras

from ingest.db import _clean

_DELETE_ORDER = ["caution_periods", "lap_exclusions", "session_quality_flags"]


def _delete_children(cur, session_id: int) -> None:
    for table in _DELETE_ORDER:
        cur.execute(f"delete from public.{table} where session_id = %s", (session_id,))


def write_cleaning_results(conn, session_id: int, caution_periods, lap_exclusions,
                            quality_flags) -> None:
    with conn:
        with conn.cursor() as cur:
            _delete_children(cur, session_id)

            if not caution_periods.empty:
                values = [(session_id, *row) for row in
                          _clean(caution_periods[["period_type", "start_time", "end_time"]])
                          .itertuples(index=False, name=None)]
                psycopg2.extras.execute_values(
                    cur,
                    "insert into public.caution_periods (session_id, period_type, start_time, end_time) values %s",
                    values,
                )

            if not lap_exclusions.empty:
                cur.execute(
                    "select id, driver_id, lap_number from public.laps where session_id = %s",
                    (session_id,),
                )
                lap_ids = {(driver_id, lap_number): lap_id for lap_id, driver_id, lap_number in cur.fetchall()}

                rows = []
                unresolved = []
                for row in lap_exclusions.itertuples(index=False):
                    lap_id = lap_ids.get((row.driver_id, row.lap_number))
                    if lap_id is None:
                        unresolved.append((row.driver_id, row.lap_number))
                        continue
                    rows.append((session_id, lap_id, row.category, row.reason))
                if unresolved:
                    raise ValueError(
                        f"lap_exclusions referenced laps not found in public.laps for session {session_id} "
                        f"(has ingestion run for this session yet?): {unresolved[:5]}"
                    )
                psycopg2.extras.execute_values(
                    cur,
                    "insert into public.lap_exclusions (session_id, lap_id, category, reason) values %s",
                    rows,
                )

            if not quality_flags.empty:
                values = [(session_id, *row) for row in
                          _clean(quality_flags[["driver_id", "issue_type", "detail"]])
                          .itertuples(index=False, name=None)]
                psycopg2.extras.execute_values(
                    cur,
                    "insert into public.session_quality_flags (session_id, driver_id, issue_type, detail) values %s",
                    values,
                )
