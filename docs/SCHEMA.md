# Data model

The schema (`supabase/schema.sql`) is designed from the actual shape of
FastF1's data rather than assumptions about it. This doc summarizes that
source data and the resulting design decisions; see the inline comments in
`schema.sql` itself for the authoritative per-table rationale.

## Source data shape (FastF1)

A race weekend has up to five sessions (FP1–3, Qualifying, Race, or with a
sprint format: FP1, Sprint Qualifying, Sprint, Qualifying, Race). Per
session, FastF1 exposes:

| Source table | Rows/session (typical) | Notes |
|---|---|---|
| `laps` | ~300–1,450 | one row per driver per lap |
| `results` | ~22 | one row per driver |
| `track_status` | ~5–25 | flag/safety-car event log |
| `session_status` | ~5–14 | session lifecycle event log |
| `weather` | ~80–210 | roughly one sample/minute |
| `race_control_messages` | ~20–265 | free-text stewarding log |
| `car_telemetry` | ~370K–985K | ~4 Hz per driver, irregular spacing |
| `position_telemetry` | ~178K–786K | independently clocked from car_telemetry |

Telemetry dominates row count by three-plus orders of magnitude over
everything else, which is the main driver of the indexing strategy (see
`docs/PERFORMANCE.md`).

Notable characteristics that shaped the schema:

- **`laps.PitInTime`/`PitOutTime`** are null unless the lap involved a pit
  stop — presence of a timestamp is the flag, not a boolean column.
- **`laps.Deleted`/`DeletedReason`** are populated by real steward
  decisions (e.g. track-limits deletions), not just a placeholder field.
- **`laps.TrackStatus`** is a string of concatenated status codes, since a
  lap can span more than one track status — not a single enum value.
- **Sector times** are frequently null on lap 1 and out-laps (partial
  sector coverage), so every sector column must allow nulls.
- **Telemetry sampling is not fixed-rate** (measured 0.16s–0.92s between
  samples, median ~0.24s) — FastF1 merges car and position streams and
  forward-fills, so timestamps must be stored per-sample rather than
  assuming a uniform sample index.
- **`car_telemetry` and `position_telemetry` are independently clocked**
  streams with different row counts even within the same session — they
  stay as two separate tables rather than being forced into one
  row-per-timestamp table, which would fabricate a join that doesn't
  exist in the source.
- **`track_status` codes** (`1` AllClear, `2` Yellow, `4` SafetyCar, `6`
  VSCDeployed, `7` VSCEnding) are the authoritative source for
  safety-car/VSC period detection in the cleaning pipeline — no need to
  infer periods from lap-time deltas.
- **`session_status`** follows a lifecycle of `Inactive → Started →
  Finished → Finalised → Ends`; `Aborted` appears for red-flagged
  sessions and is common mid-session (a red flag that resumes later in
  the same session), not itself a sign of an incomplete session — see
  `cleaning/detectors.py`'s `detect_incomplete_session`.
- **`race_control_messages`** carries a free-text `Message` plus several
  sparse, category-dependent fields (`Status`, `Flag`, `Scope`, `Sector`,
  `RacingNumber`, `Lap`) — the one genuinely semi-structured payload in
  the schema, stored as `details jsonb` on `race_control_messages`.
- **22 drivers per session**, consistently — `driver_number` is treated
  as a per-session identifier, not a stable global one; laps and
  telemetry key on the stable `driver_id` (FastF1's own id) instead,
  resolved from `driver_number` during ingestion.

## Schema design

- **Typed columns throughout.** Every field observed is fixed-shape and
  typed (RPM, speed, X/Y/Z, lap times, driver/team ids), and the largest
  tables run into tens of millions of rows — a JSONB blob per row was
  never a serious option at this scale. `race_control_messages.details`
  is the one exception, for the reason above.
- **Single-user ownership, public reads.** Every table hangs off
  `sessions` via foreign key, so ownership lives in exactly one place
  (`sessions.user_id`) and row-level security on every child table is a
  join back to its session rather than a duplicated owner column per
  table. A trigger (`keep_session_user_id`) blocks reassigning ownership
  after insert. `user_id` is still set at ingestion time for provenance,
  but it no longer gates reads -- there's nothing sensitive in a season
  of F1 telemetry, so both `anon` and `authenticated` can read every row.
- **Read-only for the frontend.** Only `SELECT` is granted to `anon`/
  `authenticated`; all writes go through the ingestion pipeline using the
  Supabase `service_role` key, which bypasses RLS by platform default.
  There is no browser-driven writer.
- **Setup revisions are tyre-only.** FastF1's public feed only exposes
  tyre configuration (compound, tyre life, fresh/used) per stint — there
  is no car setup data (wing levels, suspension, etc.) in the source.
  `setup_revisions` is scoped to exactly what's available, split from
  `stints` so a future setup dimension could be added without touching
  stint timing semantics.
- **Cleaning never mutates raw data.** The cleaning pipeline
  (`cleaning/`) never deletes or edits a row in `laps`/telemetry — every
  finding (steward deletion, timing anomaly, safety-car overlap,
  incomplete session) is an additional row in `lap_exclusions` or
  `session_quality_flags`, so raw data stays fully recoverable and every
  exclusion carries a stated reason.
- **`derived_metrics` is the other deliberate JSONB table.** It holds
  several genuinely different computation types from the analytics
  service (optimal-lap estimate, degradation regression stats, a
  telemetry delta-time trace, anomaly scores), each with its own shape —
  `subject`/`value` are jsonb; `metric_type` and the typed
  `session_id`/`driver_id` stay real columns since those are what every
  query filters on.
