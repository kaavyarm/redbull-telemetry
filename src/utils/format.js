export function formatMetric(value, unit = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }

  const formatted = Number(value).toFixed(digits);
  return unit ? `${formatted} ${unit}` : formatted;
}

// Shared by SessionsPage's weekend chips, the sidebar's session tree, and
// the command palette -- one lookup table so all three read the same
// FP1/FP2/Qualifying/Race labels.
const SESSION_TYPE_LABELS = {
  practice_1: "FP1",
  practice_2: "FP2",
  practice_3: "FP3",
  sprint_qualifying: "Sprint Qualifying",
  sprint: "Sprint",
  qualifying: "Qualifying",
  race: "Race",
};

export function sessionTypeLabel(sessionType) {
  return SESSION_TYPE_LABELS[sessionType] || sessionType;
}

export function getConfidenceClass(confidence) {
  return String(confidence || "pending").toLowerCase();
}

// insight_findings.severity is 'info'|'low'|'medium'|'high' -- not
// orderable in SQL the way its meaning implies (see lib/api.js's
// getFindings), so callers sort with this rank client-side instead.
const SEVERITY_RANK = { high: 3, medium: 2, low: 1, info: 0 };

export function getSeverityClass(severity) {
  return String(severity || "info").toLowerCase();
}

export function severityRank(severity) {
  return SEVERITY_RANK[String(severity || "info").toLowerCase()] ?? 0;
}

export function formatDelta(value, unit = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }

  const number = Number(value);
  const formatted = number.toFixed(digits);
  const signed = number > 0 ? `+${formatted}` : formatted;

  return unit ? `${signed} ${unit}` : signed;
}

// Compact "A -> B (delta)" cell for side-by-side comparison tables. Falls
// back to a plain "A -> B" for non-numeric fields (e.g. power map names),
// where a subtracted delta wouldn't mean anything.
export function formatComparison(valueA, valueB, unit = "", digits = 1) {
  if (valueA === null || valueA === undefined || valueB === null || valueB === undefined) {
    return "N/A";
  }

  if (typeof valueA === "string" || typeof valueB === "string") {
    return valueA === valueB ? String(valueA) : `${valueA} → ${valueB}`;
  }

  const delta = Number(valueB) - Number(valueA);
  return `${formatMetric(valueA, unit, digits)} → ${formatMetric(valueB, unit, digits)} (${formatDelta(delta, unit, digits)})`;
}
