-- Red Bull Telemetry — SQL analytics layer.
--
-- Run once, after supabase/schema.sql. Every view is `security_invoker`
-- (Postgres 15+, this project targets 16) so RLS on the underlying tables
-- is evaluated as the querying user, not the view's owner -- without this,
-- a view silently bypasses RLS and every `authenticated` user could read
-- every other session through it regardless of sessions.user_id.
--
-- Do not trust these against real analysis until
-- tests/test_analytics_parity.py is green -- see that file's docstring.

-- ============================================================
-- LAP TIME EVOLUTION
-- ============================================================
-- Per-lap pace context: how this lap compares to the driver's own prior
-- lap (LAG) and to their clean personal best up to that point in the
-- session (a running window MIN, conditioned on the lap not being
-- excluded -- lap_exclusions rows never removed, just filtered out of the
-- running-best calculation), and how it compares against the whole field
-- on that lap number (RANK).

create or replace view public.lap_time_evolution with (security_invoker = true) as
with lap_excl as (
  select lap_id, array_agg(distinct category order by category) as categories
  from public.lap_exclusions
  group by lap_id
),
base as (
  select
    l.id as lap_id,
    l.session_id,
    l.driver_id,
    l.lap_number,
    l.stint_id,
    l.compound,
    l.lap_time,
    (le.lap_id is not null) as is_excluded,
    coalesce(le.categories, array[]::text[]) as exclusion_categories,
    rank() over (partition by l.session_id, l.lap_number order by l.lap_time) as rank_in_lap,
    lag(l.lap_time) over (partition by l.session_id, l.driver_id order by l.lap_number) as prev_lap_time,
    min(case when le.lap_id is null then l.lap_time end) over (
      partition by l.session_id, l.driver_id
      order by l.lap_number
      rows between unbounded preceding and current row
    ) as clean_personal_best_so_far
  from public.laps l
  left join lap_excl le on le.lap_id = l.id
)
select
  *,
  lap_time - prev_lap_time as delta_to_prev_lap,
  lap_time - clean_personal_best_so_far as delta_to_clean_personal_best
from base;

grant select on public.lap_time_evolution to authenticated;

-- ============================================================
-- STINT PERFORMANCE
-- ============================================================
-- One row per (session, driver, stint): lap counts (raw and clean),
-- average/fastest clean pace, and a degradation rate in seconds/lap via
-- Postgres's built-in linear-regression aggregate (regr_slope), all
-- conditioned on lap_exclusions through FILTER rather than a WHERE clause
-- that would drop the excluded laps from lap_count too.

create or replace view public.stint_performance with (security_invoker = true) as
select
  s.session_id,
  s.driver_id,
  s.stint_number,
  s.lap_start,
  s.lap_end,
  sr.compound,
  sr.tyre_life_start,
  sr.fresh_tyre,
  count(l.id) as lap_count,
  count(l.id) filter (where le.lap_id is null) as clean_lap_count,
  avg(l.lap_time) filter (where le.lap_id is null) as avg_clean_lap_time,
  min(l.lap_time) filter (where le.lap_id is null) as fastest_clean_lap_time,
  regr_slope(extract(epoch from l.lap_time), l.lap_number) filter (where le.lap_id is null)
    as degradation_seconds_per_lap
from public.stints s
join public.laps l on l.stint_id = s.id
left join public.setup_revisions sr on sr.id = s.setup_revision_id
left join (select distinct lap_id from public.lap_exclusions) le on le.lap_id = l.id
group by s.session_id, s.driver_id, s.stint_number, s.lap_start, s.lap_end,
         sr.compound, sr.tyre_life_start, sr.fresh_tyre;

grant select on public.stint_performance to authenticated;

-- ============================================================
-- SETUP REVISION DELTAS
-- ============================================================
-- Per driver, how pace changed between one stint (tyre/setup revision) and
-- the next -- e.g. "was the switch from medium to hard actually faster or
-- slower on average." Built directly on stint_performance via LAG/LEAD
-- over a named window, reused across three window calls rather than
-- repeating the frame definition three times.

create or replace view public.setup_revision_deltas with (security_invoker = true) as
select
  session_id,
  driver_id,
  stint_number,
  compound,
  tyre_life_start,
  fresh_tyre,
  clean_lap_count,
  avg_clean_lap_time,
  degradation_seconds_per_lap,
  lag(compound) over w as prev_compound,
  lag(avg_clean_lap_time) over w as prev_avg_clean_lap_time,
  avg_clean_lap_time - lag(avg_clean_lap_time) over w as pace_delta_vs_prev_stint,
  lead(compound) over w as next_compound
from public.stint_performance
window w as (partition by session_id, driver_id order by stint_number);

grant select on public.setup_revision_deltas to authenticated;

-- ============================================================
-- COMPOUND PACE SUMMARY
-- ============================================================
-- Session-wide average pace per tyre compound. HAVING excludes compounds
-- with fewer than 3 total clean laps across all of a driver's stints on
-- them in this session -- e.g. a single lap on softs right before the
-- flag isn't a trustworthy "average pace on softs" data point. This never
-- removes the underlying laps or stints, only keeps them out of THIS
-- specific rollup, whose entire purpose is a trustworthy compound
-- comparison.

create or replace view public.compound_pace_summary with (security_invoker = true) as
select
  session_id,
  compound,
  count(*) as stint_count,
  sum(clean_lap_count) as total_clean_laps,
  avg(avg_clean_lap_time) as avg_pace,
  min(fastest_clean_lap_time) as best_lap_time,
  avg(degradation_seconds_per_lap) as avg_degradation_seconds_per_lap
from public.stint_performance
where compound is not null
group by session_id, compound
having sum(clean_lap_count) >= 3;

grant select on public.compound_pace_summary to authenticated;
