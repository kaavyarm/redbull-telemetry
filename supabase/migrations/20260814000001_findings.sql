-- insight_findings: rule-based comparative findings (Red Bull vs teammate /
-- team average / field average / session optimal). Separate from
-- derived_metrics because findings need a typed severity and a structural
-- way to reference a second driver/team, which derived_metrics' single
-- free-form subject/value jsonb pair doesn't represent cleanly.

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

alter table public.insight_findings enable row level security;

create policy "Owner can read their insight findings"
  on public.insight_findings for select to authenticated
  using (exists (
    select 1 from public.sessions s
    where s.id = insight_findings.session_id and s.user_id = auth.uid()
  ));

grant select on public.insight_findings to authenticated;
