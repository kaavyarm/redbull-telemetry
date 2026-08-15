import { useMemo } from "react";
import { getCompoundPaceSummary, getStintPerformance, getSetupRevisionDeltas, getDerivedMetrics } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { parsePgInterval } from "../../utils/telemetry";
import { formatDelta } from "../../utils/format";
import ConfidenceBadge from "../../components/ConfidenceBadge";

function seconds(interval, digits = 3) {
  const s = parsePgInterval(interval);
  return s === null ? "—" : s.toFixed(digits);
}

// stint_performance's degradation_seconds_per_lap comes straight from
// SQL's regr_slope -- no R^2/confidence there. The richer regression (with
// real confidence, from analytics/degradation.py via derived_metrics) is
// looked up per (driver_id, stint_number) below and shown alongside it.
function SetupTab({ sessionId }) {
  const { status: stintStatus, data: stints, error: stintError } = useAsync(
    () => getStintPerformance(sessionId),
    [sessionId]
  );
  const { status: compoundStatus, data: compounds } = useAsync(
    () => getCompoundPaceSummary(sessionId),
    [sessionId]
  );
  const { status: deltaStatus, data: revisionDeltas } = useAsync(
    () => getSetupRevisionDeltas(sessionId),
    [sessionId]
  );
  const { data: degradationMetrics } = useAsync(
    () => getDerivedMetrics(sessionId, "stint_degradation"),
    [sessionId]
  );

  const confidenceByStint = useMemo(() => {
    const map = new Map();
    for (const row of degradationMetrics || []) {
      map.set(`${row.driver_id}-${row.subject?.stint_number}`, row.value?.confidence);
    }
    return map;
  }, [degradationMetrics]);

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
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {stints.map((s) => {
              const confidence = confidenceByStint.get(`${s.driver_id}-${s.stint_number}`);
              return (
                <tr key={`${s.driver_id}-${s.stint_number}`}>
                  <td>{s.drivers?.full_name ?? s.driver_id}</td>
                  <td>{s.stint_number}</td>
                  <td>{s.compound ?? <ConfidenceBadge confidence="pending">unknown</ConfidenceBadge>}</td>
                  <td>{s.lap_count}</td>
                  <td>{s.clean_lap_count}</td>
                  <td>{seconds(s.avg_clean_lap_time)}</td>
                  <td>{seconds(s.fastest_clean_lap_time)}</td>
                  <td>{s.degradation_seconds_per_lap !== null ? Number(s.degradation_seconds_per_lap).toFixed(3) : "—"}</td>
                  <td>{confidence ? <ConfidenceBadge confidence={confidence}>{confidence}</ConfidenceBadge> : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {deltaStatus === "success" && revisionDeltas.length > 0 && (
        <div className="section-card" style={{ marginTop: 18 }}>
          <h3>Stint-to-stint pace delta</h3>
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Stint</th>
                <th>Prev compound</th>
                <th>Compound</th>
                <th>Next compound</th>
                <th>Pace Δ vs prev stint</th>
              </tr>
            </thead>
            <tbody>
              {revisionDeltas.map((d) => (
                <tr key={`${d.driver_id}-${d.stint_number}`}>
                  <td>{d.drivers?.full_name ?? d.driver_id}</td>
                  <td>{d.stint_number}</td>
                  <td>{d.prev_compound ?? "—"}</td>
                  <td>{d.compound ?? "—"}</td>
                  <td>{d.next_compound ?? "—"}</td>
                  <td>{formatDelta(d.pace_delta_vs_prev_stint, "s", 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default SetupTab;
