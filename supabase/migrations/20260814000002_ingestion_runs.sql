-- ingestion_runs tracks which (season, round, session_type) pulls have
-- already succeeded, so scripts/ingest_season.py can resume a long-running
-- season backfill without re-fetching/re-transforming/re-writing sessions
-- that already made it in. Pipeline-internal bookkeeping only, never read
-- by the frontend -- deliberately NOT given RLS or a grant to
-- `authenticated`, unlike every other table in schema.sql.
create table if not exists public.ingestion_runs (
  id bigint generated always as identity primary key,
  season integer not null,
  round_number integer not null,
  session_type text not null,
  status text not null check (status in ('pending', 'running', 'done', 'failed')),
  tier_summary jsonb,
  attempted_at timestamptz not null default now(),
  error text,
  unique (season, round_number, session_type)
);
