import { useMemo, useState } from "react";
import { getLaps, getLapTelemetry, getLapPosition, getSessionResults } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import {
  buildLapComparisonSeries,
  buildLapPositionSeries,
  buildLapTelemetrySeries,
  computeLapDelta,
  parsePgInterval,
} from "../../utils/telemetry";
import { formatDelta } from "../../utils/format";
import TelemetryPanelStack from "../../components/telemetry/TelemetryPanelStack";
import TrackMapPanel from "../../components/telemetry/TrackMapPanel";
import AnimatedNumber from "../../components/hud/AnimatedNumber";

function lapLabel(lap, driverName) {
  const time = lap.lap_time ? parsePgInterval(lap.lap_time).toFixed(3) + "s" : "no time";
  return `${driverName} — Lap ${lap.lap_number} (${time})`;
}

// Positive delta = lap B slower than lap A (same convention as
// computeLapDelta/analytics/similarity.py) -- colored the way a real
// timing screen would: green when B gained time, red when B lost it.
function DeltaBlock({ label, value }) {
  const direction = value === null || value === undefined ? "" : value < 0 ? "faster" : value > 0 ? "slower" : "";
  return (
    <div className={`info-block${direction ? ` ${direction}` : ""}`}>
      <p>{label}</p>
      <strong>
        <AnimatedNumber value={value} format={(v) => formatDelta(v, "s", 3)} />
      </strong>
    </div>
  );
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

  const { data: position } = useAsync(async () => {
    if (!lapAId || !lapBId) return null;
    const [a, b] = await Promise.all([getLapPosition(sessionId, lapAId), getLapPosition(sessionId, lapBId)]);
    return { a, b };
  }, [sessionId, lapAId, lapBId]);

  const [hoverTimeS, setHoverTimeS] = useState(null);

  const comparisonSeries = useMemo(
    () => (telemetry ? buildLapComparisonSeries(telemetry.a, telemetry.b) : []),
    [telemetry]
  );
  const positionSeriesA = useMemo(() => buildLapPositionSeries(position?.a || []), [position]);
  const positionSeriesB = useMemo(() => buildLapPositionSeries(position?.b || []), [position]);
  const telemetrySeriesA = useMemo(() => buildLapTelemetrySeries(telemetry?.a || []), [telemetry]);
  const telemetrySeriesB = useMemo(() => buildLapTelemetrySeries(telemetry?.b || []), [telemetry]);

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
          <DeltaBlock label="Lap time Δ" value={delta.lapTimeDeltaS} />
          <DeltaBlock label="Sector 1 Δ" value={delta.sector1DeltaS} />
          <DeltaBlock label="Sector 2 Δ" value={delta.sector2DeltaS} />
          <DeltaBlock label="Sector 3 Δ" value={delta.sector3DeltaS} />
        </div>
      )}

      <p style={{ color: "var(--muted)", fontSize: 13 }}>
        Overlay aligned by elapsed lap time, not track distance — reconstructing a shared distance
        axis from speed proved unreliable in practice, so this is the more honest basis for an
        at-a-glance overlay.
      </p>

      {telStatus === "loading" && <p>Loading telemetry…</p>}
      {telStatus === "success" && comparisonSeries.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          No telemetry recorded for one or both of these laps — full car/position telemetry is only
          kept for Red Bull's drivers and that session's closest rivals, so a lap outside that set
          has lap times and sectors but no trace to plot here. Try a different pair of laps.
        </p>
      )}
      {telStatus === "success" && comparisonSeries.length > 0 && (
        <div className="telemetry-layout">
          <TelemetryPanelStack
            series={comparisonSeries}
            syncId={`compare-${lapAId}-${lapBId}`}
            compareMode
            onHover={setHoverTimeS}
          />
          <TrackMapPanel
            series={positionSeriesA}
            seriesB={positionSeriesB}
            hoverTimeS={hoverTimeS}
            telemetrySeries={telemetrySeriesA}
            telemetrySeriesB={telemetrySeriesB}
          />
        </div>
      )}
    </div>
  );
}

export default CompareTab;
