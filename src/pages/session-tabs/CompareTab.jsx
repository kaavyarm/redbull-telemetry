import { useMemo, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { getLaps, getLapTelemetry, getSessionResults } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { buildLapComparisonSeries, computeLapDelta, parsePgInterval } from "../../utils/telemetry";
import { formatDelta } from "../../utils/format";

function lapLabel(lap, driverName) {
  const time = lap.lap_time ? parsePgInterval(lap.lap_time).toFixed(3) + "s" : "no time";
  return `${driverName} — Lap ${lap.lap_number} (${time})`;
}

function CompareTab({ sessionId }) {
  const { status: resultsStatus, data: results } = useAsync(() => getSessionResults(sessionId), [sessionId]);
  const { status: lapsStatus, data: allLaps } = useAsync(() => getLaps(sessionId), [sessionId]);

  const [lapAId, setLapAId] = useState(null);
  const [lapBId, setLapBId] = useState(null);

  const driverName = useMemo(() => {
    const map = new Map((results || []).map((r) => [r.driver_id, r.drivers?.full_name ?? r.driver_id]));
    return (driverId) => map.get(driverId) ?? driverId;
  }, [results]);

  const timedLaps = useMemo(
    () => (allLaps || []).filter((l) => l.lap_time !== null).sort((a, b) => a.driver_id.localeCompare(b.driver_id) || a.lap_number - b.lap_number),
    [allLaps]
  );

  // Default to the first two timed laps once they've loaded. Adjusted
  // during render (guarded by the null checks below) rather than in a
  // useEffect -- see hooks/useAsync.js's comment on why that avoids an
  // unnecessary extra render on load.
  if (lapAId === null && timedLaps.length) setLapAId(timedLaps[0].id);
  if (lapBId === null && timedLaps.length) setLapBId(timedLaps[1]?.id ?? timedLaps[0].id);

  const lapA = timedLaps.find((l) => l.id === lapAId);
  const lapB = timedLaps.find((l) => l.id === lapBId);

  const { status: telStatus, data: telemetry } = useAsync(async () => {
    if (!lapAId || !lapBId) return null;
    const [a, b] = await Promise.all([getLapTelemetry(sessionId, lapAId), getLapTelemetry(sessionId, lapBId)]);
    return { a, b };
  }, [sessionId, lapAId, lapBId]);

  const comparisonSeries = useMemo(
    () => (telemetry ? buildLapComparisonSeries(telemetry.a, telemetry.b) : []),
    [telemetry]
  );

  const delta = lapA && lapB ? computeLapDelta(lapA, lapB) : null;

  if (resultsStatus === "loading" || lapsStatus === "loading") {
    return <div className="section-card"><h3>Loading…</h3></div>;
  }
  if (timedLaps.length < 2) {
    return <div className="section-card"><h3>Not enough timed laps to compare</h3></div>;
  }

  return (
    <div className="control-card section-card">
      <div className="form-grid">
        <div className="control-row">
          <label>Lap A (reference)</label>
          <select value={lapAId ?? ""} onChange={(e) => setLapAId(Number(e.target.value))}>
            {timedLaps.map((l) => (
              <option key={l.id} value={l.id}>{lapLabel(l, driverName(l.driver_id))}</option>
            ))}
          </select>
        </div>
        <div className="control-row">
          <label>Lap B (comparison)</label>
          <select value={lapBId ?? ""} onChange={(e) => setLapBId(Number(e.target.value))}>
            {timedLaps.map((l) => (
              <option key={l.id} value={l.id}>{lapLabel(l, driverName(l.driver_id))}</option>
            ))}
          </select>
        </div>
      </div>

      {delta && (
        <div className="detail-grid">
          <div className="info-block">
            <p>Lap time Δ</p>
            <strong>{formatDelta(delta.lapTimeDeltaS, "s", 3)}</strong>
          </div>
          <div className="info-block">
            <p>Sector 1 Δ</p>
            <strong>{formatDelta(delta.sector1DeltaS, "s", 3)}</strong>
          </div>
          <div className="info-block">
            <p>Sector 2 Δ</p>
            <strong>{formatDelta(delta.sector2DeltaS, "s", 3)}</strong>
          </div>
          <div className="info-block">
            <p>Sector 3 Δ</p>
            <strong>{formatDelta(delta.sector3DeltaS, "s", 3)}</strong>
          </div>
        </div>
      )}

      <p style={{ color: "var(--muted)", fontSize: 13 }}>
        Overlay aligned by elapsed lap time, not track distance — reconstructing a shared distance
        axis from speed proved unreliable in practice, so this is the more honest basis for an
        at-a-glance overlay.
      </p>

      {telStatus === "loading" && <p>Loading telemetry…</p>}
      {telStatus === "success" && comparisonSeries.length > 0 && (
        <div className="chart-shell">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={comparisonSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="timeS" stroke="var(--muted)" fontSize={11} tickFormatter={(v) => v.toFixed(0)} />
              <YAxis stroke="var(--muted)" fontSize={11} />
              <Tooltip contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }} />
              <Legend />
              <Line type="monotone" dataKey="aSpeedKph" name="Lap A speed" stroke="var(--blood-bright)" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="bSpeedKph" name="Lap B speed" stroke="var(--amber)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default CompareTab;
