"""RLS policy tests against a live Postgres with supabase/schema.sql
applied (plus tests/sql/auth_shim.sql, which reproduces Supabase's
auth.uid()/authenticated/anon setup on a plain Postgres instance -- see
that file's docstring). Gated on DATABASE_URL like
tests/test_analytics_parity.py, since this needs a real database, not a
mock.

Reads are public (both `anon` and `authenticated` can read any row --
this is a single-owner portfolio project with nothing sensitive in a
season of F1 telemetry, so gating reads behind a login only added
friction without protecting anything real). Covers that end to end: any
role can read any session/laps regardless of who owns it, and writes
stay fully denied to both `anon` and `authenticated` -- only the
service_role-equivalent ingestion pipeline can write, and the ownership
trigger still blocks a user_id reassignment on that path.
"""
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set -- RLS tests need a live Postgres")

AUTH_SHIM_SQL = (Path(__file__).parent / "sql" / "auth_shim.sql").read_text()

# A season far outside any real F1 calendar, so this suite's rows are
# unambiguous to find and clean up regardless of what else is in the
# target database.
TEST_SEASON = 9999


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(DATABASE_URL)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(AUTH_SHIM_SQL)
    yield c
    c.close()


@pytest.fixture(scope="module")
def owners(conn):
    owner_a = str(uuid.uuid4())
    owner_b = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "insert into auth.users (id, email) values (%s, 'owner_a@test'), (%s, 'owner_b@test') "
            "on conflict (id) do nothing",
            (owner_a, owner_b),
        )
    yield {"a": owner_a, "b": owner_b}
    with conn.cursor() as cur:
        cur.execute("delete from auth.users where id in (%s, %s)", (owner_a, owner_b))


@pytest.fixture
def owned_session(conn, owners):
    """One session owned by owner_a, with one lap, cleaned up after the test."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into public.sessions
              (user_id, season, round_number, event_name, event_slug, event_format,
               session_type, session_name, event_date)
            values (%s, %s, 1, 'RLS Test GP', 'rls_test_gp', 'conventional', 'race', 'Race', '2099-01-01')
            returning id
            """,
            (owners["a"], TEST_SEASON),
        )
        session_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.drivers (id, full_name, abbreviation) values ('rls_test_driver', 'RLS Test', 'RLS') "
            "on conflict (id) do nothing"
        )
        cur.execute(
            "insert into public.laps (session_id, driver_id, lap_number, lap_time) "
            "values (%s, 'rls_test_driver', 1, interval '90 seconds') returning id",
            (session_id,),
        )
        lap_id = cur.fetchone()[0]
    yield {"session_id": session_id, "lap_id": lap_id}
    with conn.cursor() as cur:
        cur.execute("delete from public.sessions where id = %s", (session_id,))


@contextmanager
def as_user(conn, user_id: str | None):
    """Simulates one PostgREST request's identity: `role` claim decides
    which Postgres role the request runs as (matching how PostgREST maps a
    JWT's role claim), `sub` is what auth.uid() reads. user_id=None
    simulates an unauthenticated request (anon role, no sub claim).

    `SET x = %s` doesn't accept a bind parameter for the value in
    psycopg2 -- set_config() is the parameterized equivalent (also what
    PostgREST itself uses under the hood). `role` is never
    interpolated from user input, only one of these two hardcoded
    literals, so plain string formatting for it is safe.
    """
    role = "authenticated" if user_id else "anon"
    claims = {"sub": user_id, "role": role} if user_id else {"role": role}
    with conn.cursor() as cur:
        cur.execute(f"set role {role}")
        cur.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps(claims),))
    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("reset role")
            cur.execute("select set_config('request.jwt.claims', '', false)")


def test_owner_can_read_their_own_session(conn, owners, owned_session):
    with as_user(conn, owners["a"]):
        with conn.cursor() as cur:
            cur.execute("select id from public.sessions where id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_owner_can_read_their_own_laps(conn, owners, owned_session):
    with as_user(conn, owners["a"]):
        with conn.cursor() as cur:
            cur.execute("select id from public.laps where session_id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_different_authenticated_user_can_also_read_the_session(conn, owners, owned_session):
    """Reads are public -- who owns a row doesn't gate who can see it
    anymore, so a second authenticated user reads it just as freely as
    the owner does."""
    with as_user(conn, owners["b"]):
        with conn.cursor() as cur:
            cur.execute("select id from public.sessions where id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_different_authenticated_user_can_also_read_the_laps(conn, owners, owned_session):
    """Laps has no owner column of its own -- RLS reaches it only via the
    join back to sessions (see schema.sql's file header on why). This is
    what actually proves the join-based policy is open too, not just the
    direct policy on sessions itself."""
    with as_user(conn, owners["b"]):
        with conn.cursor() as cur:
            cur.execute("select id from public.laps where session_id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_anon_role_can_read_the_session(conn, owned_session):
    """schema.sql grants SELECT to both `anon` and `authenticated`, with
    an unconditional `using (true)` policy -- an unauthenticated request
    reads real data, not an empty/denied result."""
    with as_user(conn, None):
        with conn.cursor() as cur:
            cur.execute("select id from public.sessions where id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_anon_role_can_read_the_laps(conn, owned_session):
    """Same as above, through the join-based child-table policy rather
    than the direct policy on sessions."""
    with as_user(conn, None):
        with conn.cursor() as cur:
            cur.execute("select id from public.laps where session_id = %s", (owned_session["session_id"],))
            assert cur.fetchone() is not None


def test_authenticated_role_has_no_write_grants(conn, owners, owned_session):
    """Writes belong solely to the service_role-equivalent ingestion
    pipeline (see schema.sql's file header) -- `authenticated` must not be
    able to insert/update/delete even a row it's fully able to read."""
    with as_user(conn, owners["a"]):
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "update public.sessions set event_name = 'hacked' where id = %s",
                    (owned_session["session_id"],),
                )
    conn.rollback()


def test_anon_role_has_no_write_grants(conn, owned_session):
    """Same as above for `anon` -- opening up reads to everyone must not
    have accidentally opened up writes too."""
    with as_user(conn, None):
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "update public.sessions set event_name = 'hacked' where id = %s",
                    (owned_session["session_id"],),
                )
    conn.rollback()


def test_ownership_trigger_blocks_user_id_reassignment(conn, owners, owned_session):
    """Run as the service-role-equivalent connection (RLS/grants don't
    apply -- superuser bypasses RLS, matching how the real ingestion
    pipeline's service_role key does), which is the actual threat model
    this trigger protects against: a re-ingest upsert accidentally
    reassigning ownership, not a malicious frontend request (which can't
    even attempt an UPDATE -- see test_authenticated_role_has_no_write_grants)."""
    with conn.cursor() as cur:
        cur.execute(
            "update public.sessions set user_id = %s where id = %s",
            (owners["b"], owned_session["session_id"]),
        )
        cur.execute("select user_id from public.sessions where id = %s", (owned_session["session_id"],))
        (current_owner,) = cur.fetchone()
    assert str(current_owner) == owners["a"]
