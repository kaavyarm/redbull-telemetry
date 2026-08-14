import { useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { getLapTelemetry } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { buildLapTelemetrySeries } from "../../utils/telemetry";

function TelemetryTab({ sessionId, lapId, driverId, lapNumber }) {
  const { status, data: rows, error } = useAsync(
    () => (lapId ? getLapTelemetry(sessionId, lapId) : Promise.resolve([])),
    [sessionId, lapId]
  );

  const series = useMemo(() => buildLapTelemetrySeries(rows || []), [rows]);

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
          <span>{rows.length} samples, {series[series.length - 1].timeS.toFixed(1)}s</span>
        </div>
      </div>

      <div className="chart-shell">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="timeS" stroke="var(--muted)" fontSize={11} tickFormatter={(v) => v.toFixed(0)} />
            <YAxis stroke="var(--muted)" fontSize={11} />
            <Tooltip contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }} />
            <Legend />
            <Line type="monotone" dataKey="speedKph" name="Speed (km/h)" stroke="var(--blood-bright)" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-shell" style={{ marginTop: 18 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="timeS" stroke="var(--muted)" fontSize={11} tickFormatter={(v) => v.toFixed(0)} />
            <YAxis stroke="var(--muted)" fontSize={11} domain={[0, 100]} />
            <Tooltip contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }} />
            <Legend />
            <Line type="monotone" dataKey="throttlePct" name="Throttle %" stroke="var(--green)" dot={false} strokeWidth={2} />
            <Line type="stepAfter" dataKey="brakeOn" name="Brake" stroke="var(--amber)" dot={false} strokeWidth={1.5} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default TelemetryTab;
