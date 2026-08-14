"""Run EXPLAIN (ANALYZE, BUFFERS) against a curated set of realistic query
patterns and report planning/execution time plus whether a sequential scan
shows up on a large table. Meant to be run before and after adding indexes,
against a database with real multi-session data volume -- a single session's
worth of data makes every query 100% selective by construction, which would
make Postgres correctly choose a seq scan regardless of indexing and give a
misleading "no problem here" result.

Usage:
    DATABASE_URL=... python scripts/analyze_performance.py
"""
import os
import re
import sys

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")


def explain(cur, sql: str, params=()) -> dict:
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}", params)
    plan_lines = [row[0] for row in cur.fetchall()]
    plan_text = "\n".join(plan_lines)

    planning = re.search(r"Planning Time: ([\d.]+) ms", plan_text)
    execution = re.search(r"Execution Time: ([\d.]+) ms", plan_text)
    seq_scans = re.findall(r"Seq Scan on (\w+)", plan_text)
    index_scans = re.findall(r"Index (?:Only )?Scan.*? on (\w+)", plan_text)

    return {
        "planning_ms": float(planning.group(1)) if planning else None,
        "execution_ms": float(execution.group(1)) if execution else None,
        "seq_scans": seq_scans,
        "index_scans": index_scans,
        "plan_text": plan_text,
    }


def pick_sample_ids(cur):
    cur.execute("select id from public.sessions order by id")
    session_ids = [r[0] for r in cur.fetchall()]
    if len(session_ids) < 2:
        sys.exit(f"Need at least 2 ingested sessions for a meaningful selectivity test, found {len(session_ids)}.")

    cur.execute("select session_id, driver_id, id from public.laps where session_id = %s limit 1", (session_ids[0],))
    session_id, driver_id, lap_id = cur.fetchone()
    return session_ids, session_id, driver_id, lap_id


QUERIES = {
    "car_telemetry by session+driver, ordered by time": (
        "select * from public.car_telemetry_samples where session_id = %(session_id)s "
        "and driver_id = %(driver_id)s order by session_time", "car_telemetry_samples"
    ),
    "position_telemetry by session+driver, ordered by time": (
        "select * from public.position_telemetry_samples where session_id = %(session_id)s "
        "and driver_id = %(driver_id)s order by session_time", "position_telemetry_samples"
    ),
    "car_telemetry for one lap": (
        "select * from public.car_telemetry_samples where lap_id = %(lap_id)s", "car_telemetry_samples"
    ),
    "position_telemetry for one lap": (
        "select * from public.position_telemetry_samples where lap_id = %(lap_id)s", "position_telemetry_samples"
    ),
    "laps by session+driver, ordered by lap_number": (
        "select * from public.laps where session_id = %(session_id)s and driver_id = %(driver_id)s "
        "order by lap_number", "laps"
    ),
    "lap_time_evolution view by session": (
        "select * from public.lap_time_evolution where session_id = %(session_id)s", "laps"
    ),
    "stint_performance view by session": (
        "select * from public.stint_performance where session_id = %(session_id)s", "laps"
    ),
    "setup_revision_deltas view by session": (
        "select * from public.setup_revision_deltas where session_id = %(session_id)s", "laps"
    ),
    "compound_pace_summary view by session": (
        "select * from public.compound_pace_summary where session_id = %(session_id)s", "laps"
    ),
    "setup_revisions joined to sessions filtered by session_type": (
        "select sr.* from public.setup_revisions sr join public.sessions s on s.id = sr.session_id "
        "where s.session_type = 'race'", "setup_revisions"
    ),
}


def main():
    if not DATABASE_URL:
        sys.exit("DATABASE_URL not set")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        session_ids, session_id, driver_id, lap_id = pick_sample_ids(cur)
        print(f"sessions present: {session_ids} | testing session_id={session_id} driver_id={driver_id} lap_id={lap_id}\n")

        params = {"session_id": session_id, "driver_id": driver_id, "lap_id": lap_id}

        rows = []
        for label, (sql, watch_table) in QUERIES.items():
            result = explain(cur, sql, params)
            has_seq_scan_on_watch_table = watch_table in result["seq_scans"]
            rows.append((label, result["planning_ms"], result["execution_ms"],
                         has_seq_scan_on_watch_table, result["seq_scans"], result["index_scans"]))

        print(f"{'query':<52} {'plan(ms)':>10} {'exec(ms)':>10}  seq_scan?  scans")
        print("-" * 110)
        for label, planning, execution, has_seq, seq_scans, index_scans in rows:
            marker = "SEQ SCAN" if has_seq else "ok"
            print(f"{label:<52} {planning:>10.3f} {execution:>10.3f}  {marker:<9} "
                  f"seq={seq_scans} idx={index_scans}")

    conn.close()


if __name__ == "__main__":
    main()
