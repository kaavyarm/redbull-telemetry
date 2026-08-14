# Red Bull Telemetry — 2026 Season

A single-user analytics dashboard for Red Bull's 2026 F1 season, built on
real session data pulled from [FastF1](https://docs.fastf1.dev) (the
official F1 timing feed) rather than synthetic data. Covers session
exploration, lap-by-lap pace analysis, telemetry visualization, lap
comparison, and tire-strategy/degradation analysis.

## Architecture

```
FastF1 (live pull)
      │
      ▼
Python ingestion pipeline  ──▶  Postgres (Supabase)  ◀──  SQL analytics views
      │                              ▲                          │
      ▼                              │                          ▼
Cleaning pipeline            Python analytics service     React frontend
(data-quality flags)         (derived_metrics)             (Vite, Supabase JS)
```

- **Ingestion** (`ingest/`) — pulls a race weekend from FastF1, normalizes
  it into the relational schema, and writes it to Postgres idempotently
  (re-running a weekend replaces its rows rather than duplicating them).
- **Cleaning** (`cleaning/`) — flags deleted/anomalous laps, safety-car and
  VSC periods, and incomplete sessions. Nothing is ever deleted from the
  raw data; every exclusion is a separate row with a stated reason.
- **SQL analytics layer** (`supabase/views.sql`) — lap-time evolution,
  stint performance, and compound comparisons as Postgres views, backed by
  a pandas reference implementation (`analytics/reference.py`) that the
  views are tested against for parity.
- **Analytics service** (`analytics/`) — the pieces that don't belong in
  SQL: optimal-lap estimation, stint degradation regression, a telemetry
  delta-time trace between two laps, and per-lap anomaly detection. Runs
  as a batch job and persists results to `derived_metrics`.
- **Frontend** (`src/`) — React 19 + Vite, querying Postgres directly
  through Supabase's PostgREST API using purpose-built, narrowly-scoped
  queries (never a raw telemetry dump). Shares its design system with a
  sibling internal project.
- **Observability** (`observability/`, `src/lib/sentry.js`) — structured
  logging and optional Sentry reporting on both the Python pipeline and
  the frontend; both are no-ops when no Sentry DSN is configured.

See `docs/` for schema details, query performance notes, and the testing
strategy.

## Data model

Single-user ownership: every table hangs off `sessions` via foreign key,
and Postgres row-level security scopes every read to the signed-in user.
Telemetry and lap data are typed columns throughout (not JSON blobs) —
the schema is designed from the actual shape of FastF1's data, not
assumptions about it. See `docs/SCHEMA.md` for the full design rationale.

## Local development

Requires Node 22+, Python 3.11, Docker (for a local Supabase stack via the
Supabase CLI), and a FastF1-reachable network connection for ingestion.

```bash
# frontend
npm install
npm run dev

# python pipeline
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# local Supabase stack (Postgres + PostgREST + Auth)
supabase start
```

Copy `.env.example` to `.env.local` and fill in the local (or hosted)
Supabase project's URL/anon key for the frontend, and `DATABASE_URL` /
`SUPABASE_OWNER_USER_ID` for the Python pipeline.

```bash
python scripts/ingest_weekend.py 2026 11      # pull + ingest a weekend
python scripts/clean_weekend.py 2026 11       # flag data-quality issues
python scripts/compute_derived_metrics.py 2026 11   # run the analytics service
```

## Testing

```bash
npm test               # frontend unit tests
pytest tests/          # Python unit tests; DB-backed tests skip without DATABASE_URL
ruff check .           # Python lint
npm run lint            # frontend lint
```

See `docs/TESTING.md` for the full test strategy, including how RLS
policies and SQL/pandas parity are verified against a real database, and
`.github/workflows/ci.yml` for the CI pipeline.
