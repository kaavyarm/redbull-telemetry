"""Parity tests: supabase/views.sql vs. analytics/reference.py's independent
pandas implementation of the same metrics, across every session actually
loaded into the target database.

Requires a live Postgres with supabase/schema.sql + supabase/views.sql
applied and at least one ingested+cleaned session (see
scripts/ingest_weekend.py / scripts/clean_weekend.py) -- set DATABASE_URL to
point at it. Skipped entirely when DATABASE_URL isn't set, since this is an
integration test, not a pure-function unit test.

The SQL views in supabase/views.sql should not be trusted for real
analysis until this suite is green -- these tests are what makes that
claim checkable rather than just asserted. This file tests whatever
sessions are present in the target database, covering both conventional
and sprint-format session shapes when run against a representative set of
real weekends.
"""
import os

import numpy as np
import pandas as pd
import psycopg2
import pytest

from analytics.reference import (
    reference_compound_pace_summary,
    reference_lap_time_evolution,
    reference_setup_revision_deltas,
    reference_stint_performance,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set -- parity tests need a live Postgres")


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(DATABASE_URL)
    yield c
    c.close()


def _query(conn, sql: str, params=()) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


def _seconds_col(df: pd.DataFrame, col: str) -> pd.Series:
    """psycopg2 returns `interval` columns as datetime.timedelta (or None);
    normalize to float seconds, NaN for missing."""
    return df[col].apply(lambda v: v.total_seconds() if v is not None else np.nan)


@pytest.fixture(scope="module")
def all_session_ids(conn):
    df = _query(conn, "select id, season, round_number, session_type from public.sessions order by id")
    if df.empty:
        pytest.skip("no ingested sessions in the target database -- run scripts/ingest_weekend.py first")
    weekends = df[["season", "round_number"]].drop_duplicates()
    print(f"\nparity testing {len(df)} session(s) across {len(weekends)} weekend(s)")
    return df["id"].tolist()


def _load_base_tables(conn, session_id: int):
    laps = _query(conn, """
        select id, session_id, driver_id, lap_number, stint_id, compound, lap_time
        from public.laps where session_id = %s
    """, (session_id,))
    laps["lap_time"] = pd.to_timedelta(laps["lap_time"])

    lap_exclusions = _query(conn, """
        select le.lap_id, le.category from public.lap_exclusions le
        join public.laps l on l.id = le.lap_id
        where l.session_id = %s
    """, (session_id,))

    stints = _query(conn, """
        select id, session_id, driver_id, stint_number, lap_start, lap_end, setup_revision_id
        from public.stints where session_id = %s
    """, (session_id,))

    setup_revisions = _query(conn, """
        select id, compound, tyre_life_start, fresh_tyre from public.setup_revisions where session_id = %s
    """, (session_id,))

    return laps, lap_exclusions, stints, setup_revisions


def _assert_close(sql_val, ref_val, atol=1e-6):
    sql_nan = sql_val is None or (isinstance(sql_val, float) and np.isnan(sql_val))
    ref_nan = ref_val is None or (isinstance(ref_val, float) and np.isnan(ref_val))
    if sql_nan or ref_nan:
        assert sql_nan == ref_nan, f"NaN mismatch: sql={sql_val!r} ref={ref_val!r}"
        return
    assert abs(float(sql_val) - float(ref_val)) <= atol, f"sql={sql_val!r} ref={ref_val!r}"


# ---------------------------------------------------------------------------
# lap_time_evolution
# ---------------------------------------------------------------------------

def test_lap_time_evolution_parity(conn, all_session_ids):
    for session_id in all_session_ids:
        laps, lap_exclusions, _, _ = _load_base_tables(conn, session_id)
        if laps.empty:
            continue
        ref = reference_lap_time_evolution(laps, lap_exclusions)

        sql = _query(conn, "select * from public.lap_time_evolution where session_id = %s", (session_id,))
        for col in ["lap_time", "prev_lap_time", "clean_personal_best_so_far",
                    "delta_to_prev_lap", "delta_to_clean_personal_best"]:
            sql[f"sql_{col}_s"] = _seconds_col(sql, col)

        assert len(sql) == len(ref), f"session {session_id}: row count mismatch"

        merged = sql.merge(ref, on=["lap_id", "session_id", "driver_id", "lap_number"],
                            suffixes=("_sql", "_ref"))
        assert len(merged) == len(sql), f"session {session_id}: merge dropped rows -- key mismatch"

        for _, row in merged.iterrows():
            assert bool(row["is_excluded_sql"]) == bool(row["is_excluded_ref"])
            assert int(row["rank_in_lap_sql"]) == int(row["rank_in_lap_ref"])
            _assert_close(row["sql_lap_time_s"], row["lap_time_s"])
            _assert_close(row["sql_prev_lap_time_s"], row["prev_lap_time_s"])
            _assert_close(row["sql_delta_to_prev_lap_s"], row["delta_to_prev_lap_s"])
            _assert_close(row["sql_clean_personal_best_so_far_s"], row["clean_personal_best_so_far_s"])
            _assert_close(row["sql_delta_to_clean_personal_best_s"], row["delta_to_clean_personal_best_s"])


# ---------------------------------------------------------------------------
# stint_performance
# ---------------------------------------------------------------------------

def _sql_stint_performance(conn, session_id: int) -> pd.DataFrame:
    sql = _query(conn, "select * from public.stint_performance where session_id = %s", (session_id,))
    for col in ["avg_clean_lap_time", "fastest_clean_lap_time"]:
        sql[f"sql_{col}_s"] = _seconds_col(sql, col)
    return sql


def test_stint_performance_parity(conn, all_session_ids):
    for session_id in all_session_ids:
        laps, lap_exclusions, stints, setup_revisions = _load_base_tables(conn, session_id)
        if stints.empty:
            continue
        ref = reference_stint_performance(laps, stints, setup_revisions, lap_exclusions)
        sql = _sql_stint_performance(conn, session_id)

        assert len(sql) == len(ref), f"session {session_id}: stint row count mismatch"

        merged = sql.merge(ref, on=["session_id", "driver_id", "stint_number"], suffixes=("_sql", "_ref"))
        assert len(merged) == len(sql)

        for _, row in merged.iterrows():
            assert int(row["lap_count_sql"]) == int(row["lap_count_ref"])
            assert int(row["clean_lap_count_sql"]) == int(row["clean_lap_count_ref"])
            _assert_close(row["sql_avg_clean_lap_time_s"], row["avg_clean_lap_time_s"])
            _assert_close(row["sql_fastest_clean_lap_time_s"], row["fastest_clean_lap_time_s"])
            _assert_close(row["degradation_seconds_per_lap_sql"], row["degradation_seconds_per_lap_ref"],
                          atol=1e-4)  # regr_slope vs. manual covariance formula -- looser tolerance


# ---------------------------------------------------------------------------
# setup_revision_deltas
# ---------------------------------------------------------------------------

def test_setup_revision_deltas_parity(conn, all_session_ids):
    for session_id in all_session_ids:
        laps, lap_exclusions, stints, setup_revisions = _load_base_tables(conn, session_id)
        if stints.empty:
            continue
        stint_perf_ref = reference_stint_performance(laps, stints, setup_revisions, lap_exclusions)
        ref = reference_setup_revision_deltas(stint_perf_ref)

        sql = _query(conn, "select * from public.setup_revision_deltas where session_id = %s", (session_id,))
        for col in ["avg_clean_lap_time", "prev_avg_clean_lap_time", "pace_delta_vs_prev_stint"]:
            sql[f"sql_{col}_s"] = _seconds_col(sql, col)

        assert len(sql) == len(ref), f"session {session_id}: setup_revision_deltas row count mismatch"

        merged = sql.merge(ref, on=["session_id", "driver_id", "stint_number"], suffixes=("_sql", "_ref"))
        assert len(merged) == len(sql)

        for _, row in merged.iterrows():
            assert row["prev_compound_sql"] == row["prev_compound_ref"] or (
                pd.isna(row["prev_compound_sql"]) and pd.isna(row["prev_compound_ref"])
            )
            _assert_close(row["sql_prev_avg_clean_lap_time_s"], row["prev_avg_clean_lap_time_s"])
            _assert_close(row["sql_pace_delta_vs_prev_stint_s"], row["pace_delta_vs_prev_stint_s"])


# ---------------------------------------------------------------------------
# compound_pace_summary
# ---------------------------------------------------------------------------

def test_compound_pace_summary_parity(conn, all_session_ids):
    for session_id in all_session_ids:
        laps, lap_exclusions, stints, setup_revisions = _load_base_tables(conn, session_id)
        if stints.empty:
            continue
        stint_perf_ref = reference_stint_performance(laps, stints, setup_revisions, lap_exclusions)
        ref = reference_compound_pace_summary(stint_perf_ref)

        sql = _query(conn, "select * from public.compound_pace_summary where session_id = %s", (session_id,))
        for col in ["avg_pace", "best_lap_time"]:
            sql[f"sql_{col}_s"] = _seconds_col(sql, col)

        assert len(sql) == len(ref), f"session {session_id}: compound_pace_summary row count mismatch"
        if ref.empty:
            continue

        merged = sql.merge(ref, on=["session_id", "compound"], suffixes=("_sql", "_ref"))
        assert len(merged) == len(sql)

        for _, row in merged.iterrows():
            assert int(row["stint_count_sql"]) == int(row["stint_count_ref"])
            assert int(row["total_clean_laps_sql"]) == int(row["total_clean_laps_ref"])
            _assert_close(row["sql_avg_pace_s"], row["avg_pace_s"])
            _assert_close(row["sql_best_lap_time_s"], row["best_lap_time_s"])
            _assert_close(row["avg_degradation_seconds_per_lap_sql"], row["avg_degradation_seconds_per_lap_ref"],
                          atol=1e-4)
