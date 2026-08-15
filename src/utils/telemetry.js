// Telemetry helpers for the FastF1-sourced schema: car_telemetry_samples
// carries session_time, speed, throttle, brake, n_gear, rpm, and drs.

export function toChartNumber(value, fallback = null) {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function downsampleRows(rows, maxPoints = 400) {
  if (rows.length <= maxPoints) return rows;
  const step = Math.ceil(rows.length / maxPoints);
  return rows.filter((_, index) => index % step === 0);
}

// Postgres/PostgREST serializes `interval` columns as text, typically
// "HH:MM:SS[.ffffff]", optionally prefixed "D day(s) " for durations over
// 24h and a leading "-" for a negative interval, e.g. "-00:00:05.108".
// Negative intervals are real and common here -- lap_time_evolution's
// delta_to_prev_lap is negative every time a lap is faster than the one
// before it, so the sign has to be handled, not assumed away.
export function parsePgInterval(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return value;

  const str = String(value).trim();
  const negative = str.startsWith("-");
  const unsigned = negative ? str.slice(1) : str;

  const match = unsigned.match(/^(?:(\d+) days? )?(\d+):(\d\d):(\d\d(?:\.\d+)?)$/);
  if (!match) return null;

  const [, days, hours, minutes, secs] = match;
  const total =
    (Number(days) || 0) * 86400 + Number(hours) * 3600 + Number(minutes) * 60 + Number(secs);
  return negative ? -total : total;
}

// One lap's telemetry rows -> chart-ready points on a "seconds since this
// lap's first sample" x-axis.
export function buildLapTelemetrySeries(rows) {
  if (!rows.length) return [];
  const sorted = [...rows].sort(
    (a, b) => parsePgInterval(a.session_time) - parsePgInterval(b.session_time)
  );
  const t0 = parsePgInterval(sorted[0].session_time);

  return downsampleRows(sorted).map((row) => ({
    timeS: parsePgInterval(row.session_time) - t0,
    speedKph: toChartNumber(row.speed),
    throttlePct: toChartNumber(row.throttle),
    brakeOn: row.brake ? 1 : 0,
    nGear: toChartNumber(row.n_gear),
    rpm: toChartNumber(row.rpm),
    drs: toChartNumber(row.drs),
  }));
}

// Finds the row in a timeS-sorted series closest to a target time -- a
// linear scan, fine at the point counts used here (a few hundred at most).
// Shared by the lap-comparison resampler and the track map's cursor sync,
// so both agree on what "closest sample to this hover time" means.
export function nearestAt(series, targetTimeS) {
  return series.reduce((closest, row) =>
    Math.abs(row.timeS - targetTimeS) < Math.abs(closest.timeS - targetTimeS) ? row : closest
  );
}

// Two laps rarely share a sample count, and reconstructing a shared
// *distance* axis by integrating speed is numerically unreliable in
// practice (see analytics/similarity.py) -- re-implementing that same
// fragile technique client-side would just move the same problem into the
// browser. Aligning by elapsed time since each lap's own start is a
// deliberately simpler, more honest basis for an at-a-glance overlay: it
// won't line up two laps corner-for-corner, but every value it shows is
// exactly what was recorded, not a reconstruction that might be wrong.
export function buildLapComparisonSeries(lapARows, lapBRows, points = 150) {
  const seriesA = buildLapTelemetrySeries(lapARows);
  const seriesB = buildLapTelemetrySeries(lapBRows);
  if (!seriesA.length || !seriesB.length) return [];

  const maxTimeS = Math.min(
    seriesA[seriesA.length - 1].timeS,
    seriesB[seriesB.length - 1].timeS
  );
  if (!Number.isFinite(maxTimeS) || maxTimeS <= 0) return [];

  const step = maxTimeS / (points - 1);
  return Array.from({ length: points }, (_, index) => {
    const timeS = index * step;
    const a = nearestAt(seriesA, timeS);
    const b = nearestAt(seriesB, timeS);
    return {
      timeS,
      aSpeedKph: a.speedKph,
      bSpeedKph: b.speedKph,
      aThrottlePct: a.throttlePct,
      bThrottlePct: b.throttlePct,
      aBrakeOn: a.brakeOn,
      bBrakeOn: b.brakeOn,
      aNGear: a.nGear,
      bNGear: b.nGear,
      aRpm: a.rpm,
      bRpm: b.rpm,
      aDrs: a.drs,
      bDrs: b.drs,
    };
  });
}

// One lap's position-telemetry rows -> chart-ready points on the same
// "seconds since this lap's first sample" x-axis buildLapTelemetrySeries
// uses, so a TrackMapPanel can look up the point nearest a given hover time
// with the same nearestAt() a car-telemetry panel would use. car_telemetry
// and position_telemetry are independently clocked (see
// supabase/schema.sql), so this is its own t0, not shared with the other
// series.
export function buildLapPositionSeries(rows) {
  if (!rows.length) return [];
  const sorted = [...rows].sort(
    (a, b) => parsePgInterval(a.session_time) - parsePgInterval(b.session_time)
  );
  const t0 = parsePgInterval(sorted[0].session_time);

  return downsampleRows(sorted).map((row) => ({
    timeS: parsePgInterval(row.session_time) - t0,
    x: toChartNumber(row.x),
    y: toChartNumber(row.y),
    status: row.status,
  }));
}

function seconds(pgInterval) {
  return parsePgInterval(pgInterval);
}

// Positive deltas mean lap B was slower than lap A -- same "B minus A"
// convention as analytics/similarity.py's telemetry_delta metric, so the
// sign means the same thing whether a number came from the batch job or
// was computed here on the fly.
export function computeLapDelta(lapA, lapB) {
  if (!lapA || !lapB) return null;
  const lapTimeA = seconds(lapA.lap_time);
  const lapTimeB = seconds(lapB.lap_time);
  return {
    lapTimeDeltaS: lapTimeA !== null && lapTimeB !== null ? lapTimeB - lapTimeA : null,
    sector1DeltaS: diffOrNull(lapA.sector1_time, lapB.sector1_time),
    sector2DeltaS: diffOrNull(lapA.sector2_time, lapB.sector2_time),
    sector3DeltaS: diffOrNull(lapA.sector3_time, lapB.sector3_time),
  };
}

function diffOrNull(a, b) {
  const sa = seconds(a);
  const sb = seconds(b);
  return sa !== null && sb !== null ? sb - sa : null;
}
