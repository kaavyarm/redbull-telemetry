import { getCompoundPaceSummary, getStintPerformance } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { parsePgInterval } from "../../utils/telemetry";
import ConfidenceBadge from "../../components/ConfidenceBadge";

function seconds(interval, digits = 3) {
  const s = parsePgInterval(interval);
  return s === null ? "—" : s.toFixed(digits);
}

// stint_performance's degradation_seconds_per_lap comes straight from
// SQL's regr_slope -- no R^2/confidence there, so this reuses the
// ConfidenceBadge component but only shows it as "n laps" context, not a
// statistical confidence claim SQL didn't compute. The richer regression
// (with real confidence) lives in derived_metrics and could be wired in
// here later.
function SetupTab({ sessionId }) {
  const { status: stintStatus, data: stints, error: stintError } = useAsync(
    () => getStintPerformance(sessionId),
    [sessionId]
  );
  const { status: compoundStatus, data: compounds } = useAsync(
    () => getCompoundPaceSummary(sessionId),
    [sessionId]
  );

  if (stintStatus === "loading") return <div className="section-card"><h3>Loading…</h3></div>;
  if (stintStatus === "error") return <div className="section-card"><h3>Couldn't load setup data</h3><p>{stintError.message}</p></div>;

  return (
    <>
      <div className="section-card">
        <h3>Compound pace summary</h3>
        {compoundStatus === "success" && compounds.length === 0 && (
          <p>No compound had enough clean laps (3+) for a trustworthy average this session.</p>
        )}
        {compoundStatus === "success" && compounds.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Compound</th>
                <th>Stints</th>
                <th>Clean laps</th>
                <th>Avg pace</th>
                <th>Best lap</th>
                <th>Avg degradation (s/lap)</th>
              </tr>
            </thead>
            <tbody>
              {compounds.map((c) => (
                <tr key={c.compound}>
                  <td>{c.compound}</td>
                  <td>{c.stint_count}</td>
                  <td>{c.total_clean_laps}</td>
                  <td>{seconds(c.avg_pace)}</td>
                  <td>{seconds(c.best_lap_time)}</td>
                  <td>{c.avg_degradation_seconds_per_lap !== null ? Number(c.avg_degradation_seconds_per_lap).toFixed(3) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section-card" style={{ marginTop: 18 }}>
        <h3>Stints</h3>
        <table>
          <thead>
            <tr>
              <th>Driver</th>
              <th>Stint</th>
              <th>Compound</th>
              <th>Laps</th>
              <th>Clean laps</th>
              <th>Avg pace</th>
              <th>Fastest</th>
              <th>Degradation (s/lap)</th>
            </tr>
          </thead>
          <tbody>
            {stints.map((s) => (
              <tr key={`${s.driver_id}-${s.stint_number}`}>
                <td>{s.drivers?.full_name ?? s.driver_id}</td>
                <td>{s.stint_number}</td>
                <td>{s.compound ?? <ConfidenceBadge confidence="pending">unknown</ConfidenceBadge>}</td>
                <td>{s.lap_count}</td>
                <td>{s.clean_lap_count}</td>
                <td>{seconds(s.avg_clean_lap_time)}</td>
                <td>{seconds(s.fastest_clean_lap_time)}</td>
                <td>{s.degradation_seconds_per_lap !== null ? Number(s.degradation_seconds_per_lap).toFixed(3) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default SetupTab;
