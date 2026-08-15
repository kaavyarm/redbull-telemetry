import { parsePgInterval } from "./telemetry";

// A driver's own clean lap-time median -- the baseline every pit-loss and
// projection calculation below measures against. Median, not mean, so one
// freak lap (a red flag, a backmarker) doesn't skew the baseline.
export function computeCleanMedianPace(laps) {
  const times = laps
    .filter((l) => l.lap_time !== null && !l.deleted && !l.pit_in_time && !l.pit_out_time)
    .map((l) => parsePgInterval(l.lap_time))
    .filter((t) => t !== null)
    .sort((a, b) => a - b);
  if (!times.length) return null;
  const mid = Math.floor(times.length / 2);
  return times.length % 2 ? times[mid] : (times[mid - 1] + times[mid]) / 2;
}

// Real pit-lane time loss, derived from this driver's own data rather than
// a guessed constant: how much slower the in-lap and out-lap actually were
// than this driver's own clean median that session.
export function computeRealPitLoss(laps, pitLapNumber, cleanMedianS) {
  if (cleanMedianS === null) return null;
  const inLap = laps.find((l) => l.lap_number === pitLapNumber && l.pit_in_time);
  const outLap = laps.find((l) => l.lap_number === pitLapNumber + 1 && l.pit_out_time);
  let loss = 0;
  let found = false;
  if (inLap?.lap_time) {
    loss += parsePgInterval(inLap.lap_time) - cleanMedianS;
    found = true;
  }
  if (outLap?.lap_time) {
    loss += parsePgInterval(outLap.lap_time) - cleanMedianS;
    found = true;
  }
  return found ? Math.max(loss, 0) : null;
}

// Projects a lap time from a stint's fitted degradation regression --
// intercept_s is the fitted value at lap_in_stint = 0 (analytics/degradation.py's
// regression is 1-indexed: lap 1 of the stint is x=1), so the actual lap 1
// time is intercept_s + slope_s_per_lap, not intercept_s alone.
function projectLapTime(intercept_s, slope_s_per_lap, lapInStint) {
  return intercept_s + slope_s_per_lap * lapInStint;
}

// Simulates pitting on candidateLap instead of the actual pit lap, using
// each stint's own fitted degradation trend to project lap times outside
// the laps that were actually run in that stint. Returns null fields
// (rather than a false-precision number) when either stint's regression
// isn't trustworthy enough to extrapolate from.
export function simulateAlternatePitLap({ stintA, stintB, actualPitLap, candidateLap, pitLossS }) {
  if (pitLossS === null) return null;
  if (stintA.confidence === "insufficient_data" || stintA.confidence === "low") return null;
  if (stintB.confidence === "insufficient_data" || stintB.confidence === "low") return null;
  if (stintB.lapEnd === null || stintB.lapEnd === undefined) return null;

  const rangeStart = stintA.lapStart;
  const rangeEnd = stintB.lapEnd;
  if (candidateLap < rangeStart || candidateLap >= rangeEnd) return null;

  let simulatedTotal = 0;
  for (let lap = rangeStart; lap <= candidateLap; lap++) {
    simulatedTotal += projectLapTime(stintA.interceptS, stintA.slopeSPerLap, lap - rangeStart + 1);
  }
  simulatedTotal += pitLossS;
  for (let lap = candidateLap + 1; lap <= rangeEnd; lap++) {
    simulatedTotal += projectLapTime(stintB.interceptS, stintB.slopeSPerLap, lap - candidateLap);
  }

  let actualTotal = 0;
  for (let lap = rangeStart; lap <= actualPitLap; lap++) {
    actualTotal += projectLapTime(stintA.interceptS, stintA.slopeSPerLap, lap - rangeStart + 1);
  }
  actualTotal += pitLossS;
  for (let lap = actualPitLap + 1; lap <= rangeEnd; lap++) {
    actualTotal += projectLapTime(stintB.interceptS, stintB.slopeSPerLap, lap - actualPitLap);
  }

  return { simulatedTotalS: simulatedTotal, actualProjectedTotalS: actualTotal, deltaS: simulatedTotal - actualTotal };
}
