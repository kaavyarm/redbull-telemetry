"""Ingests + cleans the small tracked test fixtures (tests/fixtures/2026/,
see scripts/make_test_fixtures.py) into whatever DATABASE_URL points to.

Used by CI (.github/workflows/ci.yml) to get real -- if telemetry-trimmed
-- session data into the database before running the DB-gated parity/RLS/
integration tests, which otherwise have nothing to test against. Also
useful for local dev/debugging against a throwaway Postgres without the
full 242MB data/raw/ pulls.

Requires the target Postgres to already have supabase/schema.sql (and, for
parity tests, supabase/views.sql) applied, plus either a real Supabase
auth.users table or tests/sql/auth_shim.sql's stand-in.

Usage:
    python scripts/ci_seed_test_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.db import get_connection, write_session  # noqa: E402
from ingest.sources import load_session_source_from_fixture  # noqa: E402
from ingest.transform import transform_session  # noqa: E402
from cleaning.pipeline import run_cleaning_for_session  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "2026"
SESSIONS = [
    ("11_hungarian_grand_prix", "qualifying"),
    ("09_british_grand_prix", "sprint"),
]
TEST_OWNER_ID = "00000000-0000-0000-0000-000000000001"


def main():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into auth.users (id) values (%s) on conflict (id) do nothing",
                (TEST_OWNER_ID,),
            )
        conn.commit()

        for weekend_dir, session_slug in SESSIONS:
            source = load_session_source_from_fixture(FIXTURE_ROOT / weekend_dir, session_slug)
            transformed = transform_session(source)
            session_id = write_session(conn, transformed, TEST_OWNER_ID)
            counts = run_cleaning_for_session(conn, session_id)
            print(f"{weekend_dir}/{session_slug}: session_id={session_id} laps={len(transformed.laps)} "
                  f"clean={counts}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
