import { nearestAt } from "./telemetry";

// Curvature-based corner detection: no per-circuit corner data exists
// anywhere in this app (FastF1 doesn't provide it), so corners are derived
// geometrically from the lap's own x/y trace -- the heading-angle change
// at each point, smoothed to cut sensor noise, thresholded, and clustered
// so one real corner doesn't produce several adjacent "peaks".
const MIN_TURN_DEGREES = 12;
const CLUSTER_DISTANCE = 4; // index positions -- how close two turn peaks must be to merge into one corner
const SMOOTH_WINDOW = 3;

function turnAngleDegrees(p0, p1, p2) {
  const v1x = p1.x - p0.x;
  const v1y = p1.y - p0.y;
  const v2x = p2.x - p1.x;
  const v2y = p2.y - p1.y;
  const cross = v1x * v2y - v1y * v2x;
  const dot = v1x * v2x + v1y * v2y;
  return Math.abs(Math.atan2(cross, dot)) * (180 / Math.PI);
}

function movingAverage(values, window) {
  const half = Math.floor(window / 2);
  return values.map((_, i) => {
    const start = Math.max(0, i - half);
    const end = Math.min(values.length, i + half + 1);
    const slice = values.slice(start, end);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

// positionSeries: buildLapPositionSeries output. Returns corners in raw
// x/y (the same space the series is already in) numbered in lap order --
// callers scale to screen space themselves (TrackMapPanel already has a
// toScreen closure for exactly that).
export function detectCorners(positionSeries) {
  const points = (positionSeries || []).filter((p) => p.x !== null && p.y !== null);
  if (points.length < 5) return [];

  const rawTurns = points.map((p, i) =>
    i === 0 || i === points.length - 1 ? 0 : turnAngleDegrees(points[i - 1], p, points[i + 1])
  );
  const turns = movingAverage(rawTurns, SMOOTH_WINDOW);

  // Smoothing turns a single-point spike into a short plateau -- using a
  // strict ">" on one side (not ">=" on both) picks one index per plateau
  // instead of the whole flat region, which otherwise made adjacent
  // corners' candidate ranges overlap and merge into one big cluster.
  const candidates = [];
  for (let i = 1; i < turns.length - 1; i++) {
    if (turns[i] > MIN_TURN_DEGREES && turns[i] > turns[i - 1] && turns[i] >= turns[i + 1]) {
      candidates.push(i);
    }
  }

  const clusters = [];
  for (const idx of candidates) {
    const last = clusters[clusters.length - 1];
    if (last && idx - last[last.length - 1] <= CLUSTER_DISTANCE) {
      last.push(idx);
    } else {
      clusters.push([idx]);
    }
  }

  return clusters.map((cluster, i) => {
    const peakIdx = cluster.reduce((best, idx) => (turns[idx] > turns[best] ? idx : best), cluster[0]);
    const p = points[peakIdx];
    return { number: i + 1, x: p.x, y: p.y };
  });
}

// telemetrySeries: buildLapTelemetrySeries output (has timeS/brakeOn).
// positionSeries: buildLapPositionSeries output for the same lap. Brake
// 0->1 transitions are mapped to the nearest position sample by time, the
// same nearestAt() the track map's cursor sync already uses.
export function detectBrakingPoints(telemetrySeries, positionSeries) {
  if (!telemetrySeries?.length || !positionSeries?.length) return [];
  const points = [];
  for (let i = 1; i < telemetrySeries.length; i++) {
    if (telemetrySeries[i].brakeOn && !telemetrySeries[i - 1].brakeOn) {
      const nearest = nearestAt(positionSeries, telemetrySeries[i].timeS);
      if (nearest.x !== null && nearest.y !== null) {
        points.push({ x: nearest.x, y: nearest.y });
      }
    }
  }
  return points;
}
