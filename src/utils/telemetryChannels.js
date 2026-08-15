// Single source of truth for which car-telemetry channels render in the
// stacked panel view, and how -- TelemetryTab and CompareTab both import
// this instead of duplicating per-channel JSX, so a 7th channel is one
// entry here rather than a change in two files.
export const TELEMETRY_CHANNELS = [
  { key: "speedKph", label: "Speed", unit: "km/h", domain: [0, "auto"], color: "var(--blood-bright)", kind: "line" },
  { key: "throttlePct", label: "Throttle", unit: "%", domain: [0, 100], color: "var(--green)", kind: "line" },
  { key: "brakeOn", label: "Brake", unit: "", domain: [0, 1], color: "var(--amber)", kind: "step" },
  { key: "nGear", label: "Gear", unit: "", domain: [0, 8], color: "var(--muted)", kind: "step" },
  { key: "rpm", label: "RPM", unit: "", domain: [0, "auto"], color: "var(--blood-mid)", kind: "line" },
  // FastF1's drs code distinguishes several "eligible but not open" states;
  // for a compact panel, any nonzero code reads as "open" -- decoding the
  // individual status bits would need its own dedicated readout, not a
  // sixth stacked trace.
  { key: "drs", label: "DRS", unit: "", domain: [0, 1], color: "var(--muted-2)", kind: "step" },
];
