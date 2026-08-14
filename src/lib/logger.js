import { Sentry } from "./sentry";

// Structured logging for the frontend, same intent as
// observability/logging_config.py on the Python side: always log a
// structured object (event + fields), never a free-form string, so a
// query's timing/error can actually be found later instead of scrolling
// console history. Slow queries also get a Sentry breadcrumb when Sentry
// is configured, so a later-reported error's timeline shows what was slow
// leading up to it.
const SLOW_QUERY_MS = 800;

export function logEvent(level, event, fields = {}) {
  const entry = { event, ...fields };
  const consoleMethod = level === "error" ? "error" : level === "warn" ? "warn" : "log";
  console[consoleMethod](entry);
  Sentry.addBreadcrumb({ category: event, level, data: fields });
}

export function logQueryTiming(label, durationMs, error) {
  if (error) {
    logEvent("error", "query_failed", { label, duration_ms: durationMs, error: error.message });
    return;
  }
  if (durationMs >= SLOW_QUERY_MS) {
    logEvent("warn", "slow_query", { label, duration_ms: durationMs });
    return;
  }
  logEvent("debug", "query", { label, duration_ms: durationMs });
}
