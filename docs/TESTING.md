# Testing strategy

## Test layers

- **Pure-function unit tests** (`tests/test_transform.py`,
  `tests/test_cleaning.py`, `tests/test_analytics_service.py`,
  `tests/test_observability.py`) — no database required. Run against
  either hand-built malformed fixtures (to prove a detector catches a
  specific bad-data case) or real, telemetry-trimmed FastF1 pulls under
  `tests/fixtures/2026/`.
- **SQL/pandas parity tests** (`tests/test_analytics_parity.py`) — every
  SQL analytics view in `supabase/views.sql` is checked row-for-row
  against an independent pandas implementation
  (`analytics/reference.py`). The views are not considered trustworthy
  until this suite is green.
- **RLS policy tests** (`tests/test_rls.py`) — verifies the row-level
  security model end to end against a real Postgres: reads are public (a
  different authenticated user, and an unauthenticated `anon` request,
  both read any row -- including through child tables that have no owner
  column of their own and only inherit access via a join back to
  `sessions`), writes stay fully denied to both roles at the grant level
  (not just by policy), and the ownership-protection trigger blocks a
  `user_id` reassignment on the one path that can write at all (the
  service-role-equivalent ingestion pipeline).
- **Integration test** (in `tests/test_analytics_service.py`) — runs the
  full read-from-Postgres → compute → write-to-`derived_metrics` pipeline
  against a real ingested session.

Tests requiring a live database are gated on the `DATABASE_URL`
environment variable and skip cleanly when it isn't set.

## Test fixtures

`tests/test_transform.py` and part of `tests/test_cleaning.py` need real
FastF1-shaped data, not synthetic data, to be meaningful. The full pulls
under `data/raw/` are gitignored (242MB, regenerable via
`scripts/fetch_weekend.py`), so `scripts/make_test_fixtures.py` builds a
small, git-tracked copy under `tests/fixtures/2026/` (~487KB): telemetry
is evenly sampled to ~300 rows/driver (preserving time coverage across
the whole session, not just a truncated prefix — some test invariants
depend on samples existing both before and after a driver's first lap),
and the already-small tables (laps, results, track/session status,
weather, race control messages) are copied through unchanged.

`scripts/ci_seed_test_data.py` ingests and cleans these fixtures into
whatever `DATABASE_URL` points at — used by CI, and equally useful for
local development against a throwaway Postgres without a full 242MB pull.

## RLS test setup

`tests/sql/auth_shim.sql` reproduces the pieces of Supabase's platform a
plain Postgres instance doesn't have on its own: the `auth` schema, the
`authenticated`/`anon` roles, and a real `auth.uid()` implementation
(reads `request.jwt.claims->>'sub'`, exactly as Supabase's own does) —
not a simplified stub. `tests/test_rls.py` then simulates a specific
request's identity the same way PostgREST does:
`select set_config('request.jwt.claims', '{"sub": "...", "role":
"authenticated"}', false)` followed by `set role authenticated`.

## Python linting

`pyproject.toml` configures `ruff` with Pyflakes + pycodestyle correctness
rules plus `flake8-bugbear`. Notably, `zip()` calls throughout the
codebase use `strict=True` — every pairing here draws both sides from the
same DataFrame, so lengths always match today, but `strict=True` turns a
future length mismatch into an immediate `ValueError` instead of a
silently truncated result, consistent with this project's broader
principle that data-quality issues should surface loudly rather than be
silently dropped (see `cleaning/` and `docs/SCHEMA.md`).

`B008` (function-call-in-default-argument) is scoped out for `tests/*.py`
specifically rather than fixed or globally ignored: it flags test helpers
like `_clean_lap(..., lap_time=td(90))`, but `td()` returns an immutable
`pd.Timedelta`, so the shared-mutable-state bug the rule exists to catch
can't actually happen there.

## CI pipeline

`.github/workflows/ci.yml` runs seven jobs: `lint-js`, `lint-python`,
`test-js`, `build` (independent, run in parallel), `test-python-unit`
(pure-function tests, no database), `test-python-integration` (gated
behind `lint-python`/`test-python-unit` passing first, so a cheap failure
is caught before paying for a Postgres service container), and a final
`ci` job that depends on everything else — giving branch protection one
required status check to point at instead of six.

`test-python-integration` spins up a `postgres:16` service container,
applies `tests/sql/auth_shim.sql` → `supabase/schema.sql` →
`supabase/views.sql` in that order (the auth shim has to come first,
since `schema.sql`'s foreign keys reference `auth.users`), seeds the
tracked fixtures via `scripts/ci_seed_test_data.py`, then runs the full
suite against real data.

### Enabling required status checks

GitHub Actions workflow files define what runs; branch protection (which
checks must pass before a PR can merge) is separate repository
configuration, set via the GitHub web UI or `gh api`, and requires the
repo to exist on GitHub with admin access:

1. Push the repo to GitHub and let the `CI` workflow run at least once so
   GitHub knows the check names.
2. Settings → Branches → Add branch protection rule for `main`.
3. Enable "Require status checks to pass before merging" and select the
   `ci` job.
4. Optionally also enable "Require branches to be up to date before
   merging".

## Running locally

```bash
npm test                          # frontend unit tests
ruff check .                      # Python lint
pytest tests/                     # Python unit tests (DB-backed tests skip without DATABASE_URL)

# with a live database:
DATABASE_URL=postgresql://... psql "$DATABASE_URL" -f tests/sql/auth_shim.sql
DATABASE_URL=postgresql://... psql "$DATABASE_URL" -f supabase/schema.sql
DATABASE_URL=postgresql://... psql "$DATABASE_URL" -f supabase/views.sql
DATABASE_URL=postgresql://... python scripts/ci_seed_test_data.py
DATABASE_URL=postgresql://... pytest tests/ -v
```
