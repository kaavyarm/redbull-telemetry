import { useMemo, useState } from "react";
import { getLapTelemetry, getLapPosition, getDerivedMetrics, getLapExclusions } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { buildLapTelemetrySeries, buildLapPositionSeries } from "../../utils/telemetry";
import TelemetryPanelStack from "../../components/telemetry/TelemetryPanelStack";
import TrackMapPanel from "../../components/telemetry/TrackMapPanel";
import RadialGauge from "../../components/hud/RadialGauge";

function TelemetryTab({ sessionId, lapId, driverId, lapNumber }) {
  const { status, data: rows, error } = useAsync(
    () => (lapId ? getLapTelemetry(sessionId, lapId) : Promise.resolve([])),
    [sessionId, lapId]
  );
  const { data: positionRows } = useAsync(
    () => (lapId ? getLapPosition(sessionId, lapId) : Promise.resolve([])),
    [sessionId, lapId]
  );
  const { data: optimalLap } = useAsync(
    () => (lapId ? getDerivedMetrics(sessionId, "optimal_lap", driverId) : Promise.resolve([])),
    [sessionId, lapId, driverId]
  );
  const { data: exclusions } = useAsync(
    () => (lapId ? getLapExclusions(sessionId) : Promise.resolve([])),
    [sessionId, lapId]
  );

  const [hoverTimeS, setHoverTimeS] = useState(null);

  const series = useMemo(() => buildLapTelemetrySeries(rows || []), [rows]);
  const positionSeries = useMemo(() => buildLapPositionSeries(positionRows || []), [positionRows]);
  const lapExclusion = useMemo(
    () => (exclusions || []).find((e) => e.lap_id === lapId) ?? null,
    [exclusions, lapId]
  );
  const timeLeftOnTable = optimalLap?.[0]?.value?.time_left_on_table_s;

  if (!lapId) {
    return (
      <div className="section-card">
        <h3>No lap selected</h3>
        <p>Pick a lap from the Laps tab ("Telemetry" button) to see its trace here.</p>
      </div>
    );
  }

  if (status === "loading") return <div className="section-card"><h3>Loading telemetry…</h3></div>;
  if (status === "error") return <div className="section-card"><h3>Couldn't load telemetry</h3><p>{error.message}</p></div>;
  if (!series.length) return <div className="section-card"><h3>No telemetry recorded for this lap</h3></div>;

  return (
    <div className="section-card">
      <div className="chart-header">
        <div>
          <h3>{driverId} — Lap {lapNumber}</h3>
          <span>
            {rows.length} samples, {series[series.length - 1].timeS.toFixed(1)}s
            {lapExclusion && ` · excluded (${lapExclusion.category}: ${lapExclusion.reason})`}
          </span>
        </div>
        {timeLeftOnTable !== undefined && timeLeftOnTable !== null && (
          <RadialGauge
            value={Number(timeLeftOnTable)}
            min={0}
            max={2}
            unit="s"
            label="Left on table"
            tone="cyan"
            size={92}
            formatValue={(v) => v.toFixed(3)}
          />
        )}
      </div>

      <div className="telemetry-layout">
        <TelemetryPanelStack series={series} syncId={`telemetry-${lapId}`} onHover={setHoverTimeS} />
        <TrackMapPanel series={positionSeries} hoverTimeS={hoverTimeS} telemetrySeries={series} />
      </div>
    </div>
  );
}

export default TelemetryTab;
