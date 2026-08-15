import { getSessionResults } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { formatMetric } from "../../utils/format";
import { parsePgInterval } from "../../utils/telemetry";
import ExportButton from "../../components/ExportButton";

const RESULTS_CSV_COLUMNS = [
  { key: "classified_position", label: "Position" },
  { key: (r) => r.drivers?.full_name ?? r.driver_id, label: "Driver" },
  { key: (r) => r.teams?.name ?? r.team_id, label: "Team" },
  { key: "laps_completed", label: "Laps" },
  { key: (r) => formatLapTimeForCsv(r), label: "Time / Gap" },
  { key: "points", label: "Points" },
  { key: "status", label: "Status" },
];

function formatLapTimeForCsv(r) {
  return formatLapTime(r.q3 ?? r.q2 ?? r.q1 ?? r.finish_time);
}

function formatLapTime(interval) {
  const totalSeconds = parsePgInterval(interval);
  if (totalSeconds === null) return "N/A";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = (totalSeconds % 60).toFixed(3).padStart(6, "0");
  return `${minutes}:${seconds}`;
}

function ResultsTab({ sessionId }) {
  const { status, data: results, error } = useAsync(() => getSessionResults(sessionId), [sessionId]);

  if (status === "loading") return <div className="section-card"><h3>Loading…</h3></div>;
  if (status === "error") return <div className="section-card"><h3>Couldn't load results</h3><p>{error.message}</p></div>;
  if (!results.length) return <div className="section-card"><h3>No results recorded</h3></div>;

  return (
    <div className="section-card">
      <div className="table-toolbar">
        <ExportButton filename="results.csv" rows={results} columns={RESULTS_CSV_COLUMNS} />
      </div>
      <table className="results-table">
        <thead>
          <tr>
            <th>Pos</th>
            <th>Driver</th>
            <th>Team</th>
            <th>Laps</th>
            <th>Time / Gap</th>
            <th>Points</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.driver_id}>
              <td>{r.classified_position ?? "—"}</td>
              <td>{r.drivers?.full_name ?? r.driver_id}</td>
              <td style={{ color: r.teams?.color ? `#${r.teams.color}` : undefined }}>
                {r.teams?.name ?? r.team_id}
              </td>
              <td>{r.laps_completed ?? "—"}</td>
              <td>{formatLapTime(r.q3 ?? r.q2 ?? r.q1 ?? r.finish_time)}</td>
              <td>{formatMetric(r.points, "", 0)}</td>
              <td>{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ResultsTab;
