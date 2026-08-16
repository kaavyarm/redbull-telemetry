-- Red Bull Telemetry — relational schema.
--
-- Run once in the Supabase SQL Editor.
--
-- Telemetry and lap data is fixed-shape and typed (RPM, speed, X/Y/Z, lap
-- times, driver/team ids) across every session, and the largest tables run
-- into tens of millions of rows, so typed columns are used throughout
-- rather than a jsonb blob per row. The one genuinely semi-structured
-- payload is race_control_messages.details — see the comment on that
-- table for why.
--
-- Ownership is single-user: every table hangs off `sessions` via foreign
-- key, so ownership lives in exactly one place (sessions.user_id) and RLS
-- on every child table is a join back to its session rather than a
-- duplicated owner column. Ownership can only be set at INSERT time; the
-- `keep_session_user_id` trigger below blocks reassigning it on UPDATE.
--
-- Write access belongs solely to the ingestion pipeline, which
-- authenticates with the Supabase service_role key (bypasses RLS by
-- platform default) and sets sessions.user_id explicitly from a
-- SUPABASE_OWNER_USER_ID config value. There is no browser-driven writer,
-- so no insert/update/delete policies are granted to `authenticated` —
-- RLS below governs the frontend's read path only.

-- ============================================================
-- REFERENCE DATA (stable across sessions)
-- ============================================================

create table if not exists public.teams (
  id text primary key,               -- FastF1 TeamId, e.g. 'red_bull'
  name text not null,                -- TeamName
  color text                         -- TeamColor, e.g. '#3671C6'
);

create table if not exists public.drivers (
  id text primary key,               -- FastF1 DriverId, e.g. 'max_verstappen'
  full_name text not null,
  abbreviation text not null,        -- e.g. 'VER'
  broadcast_name text,
  country_code text,
  headshot_url text
);

-- ============================================================
-- SESSIONS (the ownership root — every other table hangs off this)
-- ============================================================

create table if not exists public.sessions (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id),
  season integer not null,
  round_number integer not null,
  event_name text not null,
  event_slug text not null,
  location text,
  country text,
  event_format text not null,        -- 'conventional' | 'sprint_qualifying'
  session_type text not null check (session_type in (
    'practice_1', 'practice_2', 'practice_3',
    'sprint_qualifying', 'sprint', 'qualifying', 'race'
  )),
  session_name text not null,        -- FastF1 session.name, e.g. 'Race'
  event_date date not null,
  created_at timestamptz not null default now(),
  unique (season, round_number, session_type)
);

create index if not exists sessions_user_id_idx on public.sessions(user_id);

-- ============================================================
-- SESSION RESULTS
-- ============================================================

create table if not exists public.session_results (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  team_id text references public.teams(id),
  driver_number integer not null,
  position integer,
  classified_position text,          -- often numeric, but also 'R'/'NC'/'DQ' etc.
  grid_position integer,
  q1 interval,
  q2 interval,
  q3 interval,
  finish_time interval,              -- gap to session leader, when applicable
  status text not null,              -- 'Finished' / '+1 Lap' / 'Retired' / ...
  points numeric,
  laps_completed integer,
  unique (session_id, driver_id)
);

create index if not exists session_results_session_id_idx on public.session_results(session_id);

-- ============================================================
-- TRACK STATUS / SESSION STATUS / WEATHER
-- (session-relative event logs — Time in the FastF1 source data is an
-- interval from session start, not a wall-clock timestamp, unlike
-- race_control_messages below)
-- ============================================================

create table if not exists public.track_status_events (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  occurred_at interval not null,
  status_code text not null,         -- raw FastF1 code, e.g. '1','2','4','6','7'
  message text
);

create index if not exists track_status_events_session_id_idx on public.track_status_events(session_id);

create table if not exists public.session_status_events (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  occurred_at interval not null,
  status text not null                -- 'Inactive' / 'Started' / 'Finished' / 'Aborted' / ...
);

create index if not exists session_status_events_session_id_idx on public.session_status_events(session_id);

create table if not exists public.weather_samples (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  occurred_at interval not null,
  air_temp numeric,
  humidity numeric,
  pressure numeric,
  rainfall boolean,
  track_temp numeric,
  wind_direction numeric,
  wind_speed numeric
);

create index if not exists weather_samples_session_id_idx on public.weather_samples(session_id);

-- ============================================================
-- RACE CONTROL MESSAGES
-- ============================================================
-- Time here is a wall-clock timestamp in the source data, unlike
-- track_status/session_status above. `category` and `message` are always
-- populated and are what the cleaning pipeline and analytics views
-- actually filter/read on, so they get real columns. The remaining fields
-- (status, flag, scope, sector, racing_number, lap) are sparse and vary by
-- message category — a flag message populates flag/scope/sector, a
-- lap-deletion message doesn't — which makes this the one genuinely
-- semi-structured payload in the schema.

create table if not exists public.race_control_messages (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  occurred_at timestamptz not null,
  category text not null,
  message text not null,
  details jsonb not null default '{}'::jsonb
);

create index if not exists race_control_messages_session_id_idx on public.race_control_messages(session_id);

-- ============================================================
-- SETUP REVISIONS / STINTS / LAPS
-- ============================================================
-- FastF1's public feed only exposes tyre configuration (compound, tyre
-- life, fresh/used) per stint — there is no car setup data (wing levels,
-- suspension, etc.) in the source. setup_revisions is scoped to exactly
-- what's available, split from stints so a future setup dimension (e.g.
-- parsed from FIA documents) can be added to this table without touching
-- stint timing semantics.

create table if not exists public.setup_revisions (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  compound text,                     -- SOFT / MEDIUM / HARD / INTERMEDIATE / WET.
                                      -- FastF1 leaves this and tyre_life_start null for a whole
                                      -- stint when its own tyre tracking fails to report, which
                                      -- happens in real sessions, so both columns stay nullable.
  tyre_life_start numeric,           -- TyreLife on the first lap of this revision
  fresh_tyre boolean not null,
  created_at timestamptz not null default now()
);

create index if not exists setup_revisions_session_driver_idx on public.setup_revisions(session_id, driver_id);

create table if not exists public.stints (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  stint_number integer not null,
  setup_revision_id bigint references public.setup_revisions(id),
  lap_start integer not null,
  lap_end integer,
  unique (session_id, driver_id, stint_number)
);

create index if not exists stints_session_driver_idx on public.stints(session_id, driver_id);

-- driver_number (from FastF1's per-session timing feed) is resolved to the
-- stable driver_id via that session's results during ingestion — laps/
-- telemetry key on driver_id, not the session-local driver_number.
create table if not exists public.laps (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  stint_id bigint references public.stints(id),
  lap_number integer not null,
  lap_time interval,
  lap_start_time interval,
  lap_start_date timestamptz,
  sector1_time interval,
  sector2_time interval,
  sector3_time interval,
  sector1_session_time interval,
  sector2_session_time interval,
  sector3_session_time interval,
  speed_i1 numeric,
  speed_i2 numeric,
  speed_fl numeric,
  speed_st numeric,
  is_personal_best boolean not null default false,
  compound text,
  tyre_life numeric,
  fresh_tyre boolean,
  track_status text,                 -- raw code string, can concatenate multiple codes e.g. '12'
  position integer,
  pit_in_time interval,              -- null unless this lap ended with a pit stop
  pit_out_time interval,             -- null unless this lap started with a pit exit
  deleted boolean not null default false,
  deleted_reason text,
  is_accurate boolean not null default false,
  fastf1_generated boolean not null default false,
  unique (session_id, driver_id, lap_number)
);

create index if not exists laps_session_driver_idx on public.laps(session_id, driver_id);
create index if not exists laps_stint_id_idx on public.laps(stint_id);

-- ============================================================
-- TELEMETRY SAMPLES
-- ============================================================
-- car_telemetry_samples and position_telemetry_samples stay as two tables,
-- not one. They are independently-clocked FastF1 streams with different
-- sample counts even within the same session — forcing them into one
-- row-per-timestamp table would fabricate a join that doesn't exist in
-- the source data.
--
-- lap_id is nullable and populated by ingestion only when a sample's
-- session_time unambiguously falls within one lap's bounds; out-laps,
-- in-laps, and red-flag gaps can leave it null.
--
-- Indexes below reflect two real query patterns and their EXPLAIN ANALYZE
-- profiles at multi-million-row scale:
--
-- 1. `select ... where session_id=$1 and driver_id=$2 order by session_time`
--    (the frontend's core "plot this driver's telemetry" query) needs the
--    sort order covered directly — a 2-column (session_id, driver_id)
--    index still leaves Postgres to do a separate disk-spilling sort on
--    top of the filter. The 3-column index here lets it walk the index in
--    already-sorted order and skip that sort step.
-- 2. `select ... where lap_id=$1` (the "show telemetry for this one lap"
--    query) needs its own index — without one, this is a full sequential
--    scan of the whole table to find a few hundred matching rows.

create table if not exists public.car_telemetry_samples (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  lap_id bigint references public.laps(id),
  captured_at timestamptz not null,
  session_time interval not null,
  rpm integer,
  speed numeric,
  n_gear smallint,
  throttle numeric,
  brake boolean,
  drs smallint,
  source text not null                -- 'car' | 'interpolation'
);

create index if not exists car_telemetry_samples_session_driver_time_idx
  on public.car_telemetry_samples(session_id, driver_id, session_time);
create index if not exists car_telemetry_samples_lap_id_idx
  on public.car_telemetry_samples(lap_id);

create table if not exists public.position_telemetry_samples (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text not null references public.drivers(id),
  lap_id bigint references public.laps(id),
  captured_at timestamptz not null,
  session_time interval not null,
  status text,                        -- e.g. 'OnTrack' / 'OffTrack'
  x numeric,
  y numeric,
  z numeric,
  source text not null
);

create index if not exists position_telemetry_samples_session_driver_time_idx
  on public.position_telemetry_samples(session_id, driver_id, session_time);
create index if not exists position_telemetry_samples_lap_id_idx
  on public.position_telemetry_samples(lap_id);

-- ============================================================
-- DATA QUALITY (cleaning pipeline)
-- ============================================================
-- Nothing in the cleaning pipeline deletes or mutates a row in laps/
-- telemetry — every finding is an additional row here, so raw data stays
-- recoverable and every exclusion carries a stated reason. A lap can
-- validly accumulate more than one exclusion reason, and
-- session_quality_flags.driver_id is nullable for session-wide flags
-- (which a unique constraint can't dedupe against anyway, since
-- NULL <> NULL) — idempotent re-runs delete and re-insert a session's
-- rows in these three tables in one transaction rather than relying on
-- unique constraints.

create table if not exists public.caution_periods (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  period_type text not null,          -- 'yellow' | 'safety_car' | 'vsc' | 'red_flag'
  start_time interval not null,
  end_time interval                   -- null if the period was still open when the data ended
);

create index if not exists caution_periods_session_id_idx on public.caution_periods(session_id);

create table if not exists public.lap_exclusions (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  lap_id bigint not null references public.laps(id) on delete cascade,
  category text not null,             -- 'steward_deleted' | 'pit_lap' | 'caution_period' | 'timing_anomaly' | 'low_confidence'
  reason text not null,
  created_at timestamptz not null default now()
);

create index if not exists lap_exclusions_session_id_idx on public.lap_exclusions(session_id);
create index if not exists lap_exclusions_lap_id_idx on public.lap_exclusions(lap_id);

create table if not exists public.session_quality_flags (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text references public.drivers(id),   -- null = session-wide flag
  issue_type text not null,           -- 'incomplete_session' | 'red_flag_interruption' | 'missing_car_telemetry' | 'missing_position_telemetry' | 'missing_channel'
  detail text,
  created_at timestamptz not null default now()
);

create index if not exists session_quality_flags_session_id_idx on public.session_quality_flags(session_id);

-- ============================================================
-- DERIVED METRICS (analytics service)
-- ============================================================
-- Everything upstream is uniform-shape data, which is why it gets normal
-- typed columns instead of JSONB. This table is the deliberate exception:
-- it holds several genuinely different computation types (optimal-lap
-- estimate, stint degradation regression stats, a telemetry delta-time
-- trace between two laps, per-lap telemetry anomaly scores), each with
-- its own distinct shape, produced by a batch job that runs after
-- ingestion and cleaning. `subject` and `value` are jsonb for that
-- reason; `metric_type` and the typed session_id/driver_id stay real
-- columns because those are what every query actually filters on.

create table if not exists public.derived_metrics (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  driver_id text references public.drivers(id),   -- null = session-wide metric (e.g. session optimal lap)
  metric_type text not null,          -- 'optimal_lap' | 'stint_degradation' | 'telemetry_delta' | 'lap_anomaly'
  subject jsonb not null,             -- what this metric is about, e.g. {"stint_number": 2} or {"lap_a": 12, "lap_b": 45}
  value jsonb not null,               -- the computed payload; shape depends on metric_type
  computed_at timestamptz not null default now()
);

create index if not exists derived_metrics_session_id_idx on public.derived_metrics(session_id);
create index if not exists derived_metrics_session_type_idx on public.derived_metrics(session_id, metric_type);

-- insight_findings is a separate table rather than another derived_metrics
-- metric_type because findings need a typed severity and a structural way
-- to reference a second driver/team being compared against -- derived_metrics'
-- single free-form subject/value jsonb pair doesn't represent "this driver
-- vs that driver" cleanly. The flat, typed shape here (finding_type,
-- severity, subject/compared-against columns, a plain-language message) is
-- deliberate: a future narration layer can read rows directly without a
-- schema change.
create table if not exists public.insight_findings (
  id bigint generated always as identity primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  finding_type text not null,        -- 'stint_degradation_vs_field' | 'sector_time_vs_teammate' | 'time_left_on_table'
  severity text not null check (severity in ('info', 'low', 'medium', 'high')),
  subject_driver_id text not null references public.drivers(id),
  compared_against_type text not null check (
    compared_against_type in ('teammate', 'team_avg', 'field_avg', 'session_optimal')
  ),
  compared_against_driver_id text references public.drivers(id),  -- set only for 'teammate'
  compared_against_team_id text references public.teams(id),      -- set only for 'team_avg'
  metric_value numeric,
  threshold_value numeric,
  unit text,                          -- 's' | 's_per_lap' | 'm' | 'pct'
  subject jsonb not null default '{}'::jsonb,
  message text not null,               -- plain-language rendering
  computed_at timestamptz not null default now()
);

create index if not exists insight_findings_session_id_idx on public.insight_findings(session_id);
create index if not exists insight_findings_session_driver_idx on public.insight_findings(session_id, subject_driver_id);

-- ingestion_runs tracks which (season, round, session_type) pulls have
-- already succeeded, so scripts/ingest_season.py can resume a long-running
-- season backfill without re-fetching/re-transforming/re-writing sessions
-- that already made it in. Pipeline-internal bookkeeping only, never read
-- by the frontend -- deliberately NOT given RLS or a grant to
-- `authenticated`, unlike every other table in this file.
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

-- ============================================================
-- OWNERSHIP PROTECTION
-- ============================================================
-- Since ownership lives only on sessions, only one trigger is needed. It
-- forces sessions.user_id back to its existing value on every UPDATE
-- regardless of what the caller sends — ownership can only be set at
-- INSERT time.

create or replace function public.keep_session_user_id() returns trigger as $$
begin
  new.user_id := old.user_id;
  return new;
end;
$$ language plpgsql security definer set search_path = public;

create trigger sessions_keep_user_id
  before update on public.sessions
  for each row execute function public.keep_session_user_id();

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
-- Public read-only, to both `anon` and `authenticated` -- there's nothing
-- sensitive in a season's worth of F1 telemetry, and this is a single-
-- owner portfolio project with no per-user data to isolate, so gating
-- reads behind a login only added friction for anyone looking at it
-- without actually protecting anything. Writes are still not exposed to
-- either role at all; the ingestion pipeline writes via the service_role
-- key, which bypasses RLS by Supabase platform default. `user_id` stays
-- on every table as an ingestion-time ownership/provenance column (see
-- the file header), it just isn't used to filter reads anymore.

alter table public.teams enable row level security;
alter table public.drivers enable row level security;
alter table public.sessions enable row level security;
alter table public.session_results enable row level security;
alter table public.track_status_events enable row level security;
alter table public.session_status_events enable row level security;
alter table public.weather_samples enable row level security;
alter table public.race_control_messages enable row level security;
alter table public.setup_revisions enable row level security;
alter table public.stints enable row level security;
alter table public.laps enable row level security;
alter table public.car_telemetry_samples enable row level security;
alter table public.position_telemetry_samples enable row level security;
alter table public.caution_periods enable row level security;
alter table public.lap_exclusions enable row level security;
alter table public.session_quality_flags enable row level security;
alter table public.derived_metrics enable row level security;
alter table public.insight_findings enable row level security;

-- Reference tables (teams, drivers) aren't owned by any one session, so
-- they're readable directly rather than joined through sessions.
create policy "Anyone can read teams"
  on public.teams for select to anon, authenticated using (true);

create policy "Anyone can read drivers"
  on public.drivers for select to anon, authenticated using (true);

create policy "Anyone can read sessions"
  on public.sessions for select to anon, authenticated
  using (true);

create policy "Anyone can read session_results"
  on public.session_results for select to anon, authenticated
  using (true);

create policy "Anyone can read track_status_events"
  on public.track_status_events for select to anon, authenticated
  using (true);

create policy "Anyone can read session_status_events"
  on public.session_status_events for select to anon, authenticated
  using (true);

create policy "Anyone can read weather_samples"
  on public.weather_samples for select to anon, authenticated
  using (true);

create policy "Anyone can read race_control_messages"
  on public.race_control_messages for select to anon, authenticated
  using (true);

create policy "Anyone can read setup_revisions"
  on public.setup_revisions for select to anon, authenticated
  using (true);

create policy "Anyone can read stints"
  on public.stints for select to anon, authenticated
  using (true);

create policy "Anyone can read laps"
  on public.laps for select to anon, authenticated
  using (true);

create policy "Anyone can read car_telemetry"
  on public.car_telemetry_samples for select to anon, authenticated
  using (true);

create policy "Anyone can read position_telemetry"
  on public.position_telemetry_samples for select to anon, authenticated
  using (true);

create policy "Anyone can read caution_periods"
  on public.caution_periods for select to anon, authenticated
  using (true);

create policy "Anyone can read lap_exclusions"
  on public.lap_exclusions for select to anon, authenticated
  using (true);

create policy "Anyone can read session_quality_flags"
  on public.session_quality_flags for select to anon, authenticated
  using (true);

create policy "Anyone can read derived_metrics"
  on public.derived_metrics for select to anon, authenticated
  using (true);

create policy "Anyone can read insight_findings"
  on public.insight_findings for select to anon, authenticated
  using (true);

-- ============================================================
-- GRANTS
-- ============================================================
-- RLS policies control which rows a role can touch, but Postgres still
-- requires a base table-level GRANT before RLS is even evaluated. Only
-- SELECT is granted to either role -- see the file header on why writes
-- aren't exposed to the frontend at all.

grant usage on schema public to anon, authenticated;
grant select on public.teams to anon, authenticated;
grant select on public.drivers to anon, authenticated;
grant select on public.sessions to anon, authenticated;
grant select on public.session_results to anon, authenticated;
grant select on public.track_status_events to anon, authenticated;
grant select on public.session_status_events to anon, authenticated;
grant select on public.weather_samples to anon, authenticated;
grant select on public.race_control_messages to anon, authenticated;
grant select on public.setup_revisions to anon, authenticated;
grant select on public.stints to anon, authenticated;
grant select on public.laps to anon, authenticated;
grant select on public.car_telemetry_samples to anon, authenticated;
grant select on public.position_telemetry_samples to anon, authenticated;
grant select on public.caution_periods to anon, authenticated;
grant select on public.lap_exclusions to anon, authenticated;
grant select on public.session_quality_flags to anon, authenticated;
grant select on public.derived_metrics to anon, authenticated;
grant select on public.insight_findings to anon, authenticated;
