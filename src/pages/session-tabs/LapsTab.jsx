import { useMemo, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { getLapTimeEvolution, getSessionResults } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { parsePgInterval } from "../../utils/telemetry";

function LapsTab({ sessionId, onViewTelemetry }) {
  const { status: resultsStatus, data: results } = useAsync(() => getSessionResults(sessionId), [sessionId]);
  const [driverId, setDriverId] = useState(null);

  const effectiveDriverId = driverId ?? results?.[0]?.driver_id ?? null;

  const { status, data: laps, error } = useAsync(
    () => (effectiveDriverId ? getLapTimeEvolution(sessionId, effectiveDriverId) : Promise.resolve([])),
    [sessionId, effectiveDriverId]
  );

  const chartData = useMemo(
    () =>
      (laps || [])
        .filter((l) => l.lap_time !== null)
        .map((l) => ({ lapNumber: l.lap_number, lapTimeS: parsePgInterval(l.lap_time), excluded: l.is_excluded })),
    [laps]
  );

  if (resultsStatus === "loading") return <div className="section-card"><h3>Loading…</h3></div>;

  return (
    <div className="section-card">
      <div className="control-row" style={{ maxWidth: 280, marginBottom: 18 }}>
        <label>Driver</label>
        <select value={effectiveDriverId ?? ""} onChange={(e) => setDriverId(e.target.value)}>
          {results.map((r) => (
            <option key={r.driver_id} value={r.driver_id}>
              {r.drivers?.full_name ?? r.driver_id}
            </option>
          ))}
        </select>
      </div>

      {status === "loading" && <p>Loading laps…</p>}
      {status === "error" && <p className="auth-error">{error.message}</p>}

      {status === "success" && (
        <>
          <div className="chart-header">
            <div>
              <h3>Lap time evolution</h3>
              <span>Faded points were excluded from clean-pace analysis — hover for why.</span>
            </div>
          </div>
          <div className="chart-shell">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="lapNumber" stroke="var(--muted)" fontSize={11} />
                <YAxis stroke="var(--muted)" fontSize={11} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }}
                  formatter={(value) => `${value.toFixed(3)}s`}
                />
                <Line type="monotone" dataKey="lapTimeS" stroke="var(--blood-bright)" dot={{ r: 2 }} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <table style={{ marginTop: 18 }}>
            <thead>
              <tr>
                <th>Lap</th>
                <th>Time</th>
                <th>Δ prev</th>
                <th>Rank</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {laps.map((l) => (
                <tr key={l.lap_number} className={l.is_excluded ? "excluded-row" : ""}>
                  <td>{l.lap_number}</td>
                  <td>{l.lap_time ? parsePgInterval(l.lap_time).toFixed(3) : "—"}</td>
                  <td>{l.delta_to_prev_lap ? parsePgInterval(l.delta_to_prev_lap).toFixed(3) : "—"}</td>
                  <td>{l.rank_in_lap ?? "—"}</td>
                  <td>{l.is_excluded ? (l.exclusion_categories || []).join(", ") : "clean"}</td>
                  <td>
                    <button className="secondary-button" onClick={() => onViewTelemetry(l.lap_id, effectiveDriverId, l.lap_number)}>
                      Telemetry
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export default LapsTab;
