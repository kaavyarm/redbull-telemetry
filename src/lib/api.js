import { supabase } from "./supabaseClient";
import { logQueryTiming } from "./logger";

// Every query here is purpose-built for exactly the screen that calls it --
// scoped by session_id (and often driver_id/lap_id too) and selecting only
// the columns that screen renders. None of these ever pull raw telemetry
// for more than one lap at a time; car_telemetry_samples/
// position_telemetry_samples are only ever queried by (session_id, lap_id),
// which is covered by a dedicated index (see supabase/schema.sql).
//
// Every query and auth call goes through runQuery/runAuth so timing is
// measured and logged in exactly one place rather than repeated at every
// call site.

async function runQuery(label, queryBuilder) {
  const start = performance.now();
  const { data, error } = await queryBuilder;
  const durationMs = Math.round(performance.now() - start);
  logQueryTiming(label, durationMs, error);
  if (error) throw error;
  return data;
}

async function runAuth(label, authPromise) {
  const start = performance.now();
  const { data, error } = await authPromise;
  const durationMs = Math.round(performance.now() - start);
  logQueryTiming(label, durationMs, error);
  if (error) throw error;
  return data;
}

export async function listSessions() {
  return runQuery(
    "listSessions",
    supabase
      .from("sessions")
      .select("id, season, round_number, event_name, location, country, event_format, session_type, session_name, event_date")
      .order("event_date", { ascending: false })
      .order("round_number", { ascending: false })
  );
}

export async function getSession(sessionId) {
  return runQuery("getSession", supabase.from("sessions").select("*").eq("id", sessionId).single());
}

export async function getSessionResults(sessionId) {
  return runQuery(
    "getSessionResults",
    supabase
      .from("session_results")
      .select(
        "driver_id, team_id, driver_number, position, classified_position, grid_position, q1, q2, q3, finish_time, status, points, laps_completed, drivers(full_name, abbreviation, headshot_url), teams(name, color)"
      )
      .eq("session_id", sessionId)
      .order("position", { ascending: true, nullsFirst: false })
  );
}

export async function getLaps(sessionId, driverId = null) {
  let query = supabase
    .from("laps")
    .select(
      "id, driver_id, lap_number, lap_time, sector1_time, sector2_time, sector3_time, compound, deleted, is_accurate, pit_in_time, pit_out_time"
    )
    .eq("session_id", sessionId)
    .order("lap_number", { ascending: true });
  if (driverId) query = query.eq("driver_id", driverId);
  return runQuery("getLaps", query);
}

export async function getLapTimeEvolution(sessionId, driverId = null) {
  let query = supabase
    .from("lap_time_evolution")
    .select("*")
    .eq("session_id", sessionId)
    .order("lap_number", { ascending: true });
  if (driverId) query = query.eq("driver_id", driverId);
  return runQuery("getLapTimeEvolution", query);
}

export async function getStintPerformance(sessionId) {
  return runQuery(
    "getStintPerformance",
    supabase
      .from("stint_performance")
      .select("*, drivers(full_name, abbreviation)")
      .eq("session_id", sessionId)
      .order("driver_id")
      .order("stint_number")
  );
}

export async function getSetupRevisionDeltas(sessionId) {
  return runQuery(
    "getSetupRevisionDeltas",
    supabase
      .from("setup_revision_deltas")
      .select("*, drivers(full_name, abbreviation)")
      .eq("session_id", sessionId)
      .order("driver_id")
      .order("stint_number")
  );
}

export async function getCompoundPaceSummary(sessionId) {
  return runQuery(
    "getCompoundPaceSummary",
    supabase.from("compound_pace_summary").select("*").eq("session_id", sessionId).order("avg_pace", { ascending: true })
  );
}

// The one telemetry query in the whole app -- always scoped to a single
// lap via the (session_id, lap_id) index, never a whole-session pull.
export async function getLapTelemetry(sessionId, lapId) {
  return runQuery(
    "getLapTelemetry",
    supabase
      .from("car_telemetry_samples")
      .select("session_time, speed, throttle, brake, n_gear, rpm, drs")
      .eq("session_id", sessionId)
      .eq("lap_id", lapId)
      .order("session_time", { ascending: true })
  );
}

// Position telemetry's own (session_id, lap_id) index covers this the same
// way car_telemetry_samples' does -- same single-lap scoping as getLapTelemetry.
export async function getLapPosition(sessionId, lapId) {
  return runQuery(
    "getLapPosition",
    supabase
      .from("position_telemetry_samples")
      .select("session_time, x, y, z, status")
      .eq("session_id", sessionId)
      .eq("lap_id", lapId)
      .order("session_time", { ascending: true })
  );
}

export async function getLapExclusions(sessionId) {
  return runQuery(
    "getLapExclusions",
    supabase.from("lap_exclusions").select("lap_id, category, reason").eq("session_id", sessionId)
  );
}

export async function getDerivedMetrics(sessionId, metricType, driverId = undefined) {
  let query = supabase
    .from("derived_metrics")
    .select("driver_id, subject, value")
    .eq("session_id", sessionId)
    .eq("metric_type", metricType);
  if (driverId !== undefined) {
    query = driverId === null ? query.is("driver_id", null) : query.eq("driver_id", driverId);
  }
  return runQuery("getDerivedMetrics", query);
}

// severity is a text column ('info'|'low'|'medium'|'high'), so it isn't
// orderable in SQL the way its meaning implies -- callers sort client-side
// with utils/format.js's severityRank instead.
export async function getFindings(sessionId, { severity, driverId } = {}) {
  let query = supabase
    .from("insight_findings")
    .select(
      "finding_type, severity, subject_driver_id, compared_against_type, compared_against_driver_id, compared_against_team_id, metric_value, threshold_value, unit, subject, message, computed_at, drivers!insight_findings_subject_driver_id_fkey(full_name, abbreviation)"
    )
    .eq("session_id", sessionId)
    .order("computed_at", { ascending: false });
  if (severity) query = query.eq("severity", severity);
  if (driverId) query = query.eq("subject_driver_id", driverId);
  return runQuery("getFindings", query);
}

// -- auth --

export async function signInWithPassword(email, password) {
  return runAuth("signInWithPassword", supabase.auth.signInWithPassword({ email, password }));
}

export async function signOut() {
  return runAuth("signOut", supabase.auth.signOut());
}

export function getCurrentSession() {
  return supabase.auth.getSession();
}

export function onAuthStateChange(callback) {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => callback(session));
  return data.subscription;
}
