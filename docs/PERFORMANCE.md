# Performance

## Database query performance

Tested with `scripts/analyze_performance.py` against a Postgres 16 instance
running `supabase/schema.sql` + `supabase/views.sql`, loaded with two
full-scale, untruncated real race sessions (via `scripts/ingest_weekend.py`
+ `scripts/clean_weekend.py`):

| table | rows |
|---|---|
| car_telemetry_samples | 1,752,344 |
| position_telemetry_samples | 963,974 |
| laps | 2,883 |

Two sessions, not one, deliberately: filtering `WHERE session_id = $1`
against a database holding only that one session matches 100% of the
table, so Postgres correctly picks a sequential scan regardless of
indexing — which would make an index look pointless when, in production
with dozens of sessions, the same filter is highly selective. Two sessions
is the minimum that makes the selectivity real.

## Findings and fixes

### 1. `lap_id` had no index at all — fixed

The "show telemetry for this one lap" query (`WHERE lap_id = $1`), needed
for a per-lap telemetry trace, had nothing to use but a full scan.

```
Before: Parallel Seq Scan on car_telemetry_samples (3 workers)
        Rows Removed by Filter: 584,003 (of ~1.75M)
        Execution Time: 847.4 ms   (position_telemetry: 812.9 ms)

After:  Index Scan using car_telemetry_samples_lap_id_idx
        Execution Time: 1.8 ms     (position_telemetry: 1.6 ms)
```

~470x faster on car_telemetry, ~500x on position_telemetry. Added
`car_telemetry_samples_lap_id_idx` / `position_telemetry_samples_lap_id_idx`
(plain btree on `lap_id`).

### 2. Session+driver telemetry query was paying for an unindexed sort — fixed, with a caveat

The core "plot this driver's telemetry for the session" query
(`WHERE session_id=$1 AND driver_id=$2 ORDER BY session_time`) used the
existing `(session_id, driver_id)` index to filter, but Postgres still had
to run a separate disk-spilling external sort afterward to satisfy
`ORDER BY session_time`, since the index didn't cover that column.

Extended the index to `(session_id, driver_id, session_time)` so a plain
index scan returns rows already in order. Isolated the index's effect from
Postgres's scan-choice cost model by testing both the old and new index
under the same `random_page_cost` setting:

```
Same random_page_cost=1.1 (SSD-realistic) both sides:
Before (2-col index, external sort): Execution Time: 457.9 ms
After  (3-col covering index):       Execution Time: 154.0 ms
```

~3x faster, attributable purely to the index change.

Caveat: under the test container's default `random_page_cost=4` (tuned
for spinning disks, not representative of Supabase's SSD-backed managed
Postgres), the planner still preferred a Bitmap Heap Scan + sort over the
new covering index's plain Index Scan (~400ms either way) — a cost-model
choice, not a missing index. The fix is real and proven above, but whether
Postgres picks the fast plan automatically depends on `random_page_cost`
being tuned for the actual storage backend. Worth re-checking
`EXPLAIN ANALYZE` on this query against the production Supabase project;
if it still chooses a bitmap+sort plan there, that's a `random_page_cost`
tuning question, not a schema problem.

### 3. Every other "sequential scan" flagged was correct planner behavior, not a problem

`lap_time_evolution`, `stint_performance`, `setup_revision_deltas`,
`compound_pace_summary`, and the `setup_revisions` ⋈ `sessions` join all
show `Seq Scan` on `laps` / `stints` / `setup_revisions` / `lap_exclusions`
/ `sessions` in the plan. Real row counts, checked before concluding
anything: all of these tables are between 2 and 2,883 rows even with two
full sessions loaded.

```
laps: 2,883 | lap_exclusions: 1,017 | stints: 175 | setup_revisions: 175
session_results: 44 | caution_periods: 13 | sessions: 2
```

At this size, a sequential scan is faster than an index scan (fits in a
handful of pages, no random I/O or index traversal overhead) — Postgres is
making the right call. No index added here. These views' execution times
(55–100ms) are dominated by the window functions and joins themselves, not
by how the base tables are scanned, and stay well within interactive
latency at this scale.

## Final index set (car/position telemetry tables)

```sql
create index car_telemetry_samples_session_driver_time_idx
  on car_telemetry_samples(session_id, driver_id, session_time);
create index car_telemetry_samples_lap_id_idx
  on car_telemetry_samples(lap_id);

create index position_telemetry_samples_session_driver_time_idx
  on position_telemetry_samples(session_id, driver_id, session_time);
create index position_telemetry_samples_lap_id_idx
  on position_telemetry_samples(lap_id);
```

These replace (not add alongside) a plain 2-column `(session_id,
driver_id)` index — the 3-column index still serves any query that
filters on just the first two columns (leftmost-prefix matching), so
keeping both would only add write overhead on a multi-million-row,
write-heavy table for no read benefit.

## Full before/after query table

All timings from `EXPLAIN (ANALYZE, BUFFERS)`, default container
`random_page_cost` unless noted, single run (not averaged).

| query | before (ms) | after (ms) |
|---|---|---|
| car_telemetry by session+driver, ordered by time | 401.9 | 437.4 (154.0 at rpc=1.1, isolated) |
| position_telemetry by session+driver, ordered by time | 384.6 | 397.0 |
| car_telemetry for one lap | 1605.1 | 1.8 |
| position_telemetry for one lap | 812.9 | 1.6 |
| laps by session+driver, ordered by lap_number | 3.0 | 0.6 |
| lap_time_evolution view by session | 113.9 | 100.2 |
| stint_performance view by session | 61.1 | 69.5 |
| setup_revision_deltas view by session | 68.1 | 66.5 |
| compound_pace_summary view by session | 58.6 | 55.1 |
| setup_revisions ⋈ sessions by session_type | 2.1 | 1.9 |

## Frontend payload sizes

Measured with `scripts/measure_payloads.sh` against a live PostgREST
instance backed by a real ingested race session (1,431 laps; full
untruncated telemetry kept for 2 drivers so the single-lap query numbers
below are honest, not a truncated sample):

| Query | Payload | Time |
|---|---|---|
| `listSessions()` | 220 B | 0.13 s |
| `getSessionResults()` | 11.1 KB | 0.25 s |
| `getLapTimeEvolution(driver)` | 23.7 KB | 0.78 s |
| `getLaps(all, session)` (lap comparison picker) | 365 KB | ~0.4–2 s |
| `getStintPerformance()` | 24.4 KB | 0.57 s |
| `getCompoundPaceSummary()` | 0.5 KB | 0.22 s |
| `getSetupRevisionDeltas()` | 27.3 KB | 0.41 s |
| `getLapTelemetry(lap_id)` (the one telemetry query) | 35.9 KB | 0.10 s |
| *For comparison: a naive whole-session telemetry download* | 15,506 KB | 42.6 s |

The frontend never queries telemetry except by `(session_id, lap_id)` —
`getLapTelemetry` is roughly 430x smaller and 420x faster than a naive
whole-session download would be, which is why every telemetry chart in
the UI is scoped to a single lap rather than offering a bulk export.

Production JS bundle (`npm run build`): 789.6 KB raw / 224.8 KB gzipped,
12.9 KB CSS.
