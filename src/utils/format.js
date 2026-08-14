export function formatMetric(value, unit = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }

  const formatted = Number(value).toFixed(digits);
  return unit ? `${formatted} ${unit}` : formatted;
}

export function getConfidenceClass(confidence) {
  return String(confidence || "pending").toLowerCase();
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
