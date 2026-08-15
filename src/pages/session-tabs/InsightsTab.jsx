import { useMemo } from "react";
import { getFindings } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { severityRank } from "../../utils/format";
import SeverityBadge from "../../components/SeverityBadge";

const COMPARED_AGAINST_LABEL = {
  teammate: "vs teammate",
  team_avg: "vs team average",
  field_avg: "vs field average",
  session_optimal: "vs session optimal",
};

function driverLabel(driverId, driverRow) {
  return driverRow?.full_name ?? driverId;
}

function InsightsTab({ sessionId }) {
  const { status, data: findings, error } = useAsync(() => getFindings(sessionId), [sessionId]);

  const sorted = useMemo(
    () => [...(findings || [])].sort((a, b) => severityRank(b.severity) - severityRank(a.severity)),
    [findings]
  );

  if (status === "loading") return <div className="section-card"><h3>Loading…</h3></div>;
  if (status === "error") return <div className="section-card"><h3>Couldn't load insights</h3><p>{error.message}</p></div>;
  if (!sorted.length) {
    return (
      <div className="section-card">
        <h3>No findings for this session</h3>
        <p>Either nothing crossed a rule's threshold, or scripts/compute_insights.py hasn't run for this session yet.</p>
      </div>
    );
  }

  return (
    <div className="section-card">
      {sorted.map((f, index) => (
        <div
          key={index}
          className={`reveal${index > 0 ? " finding-card-footer" : ""}${f.severity === "high" ? " scan-once" : ""}`}
          style={{ "--i": index }}
        >
          <div className="finding-card-header">
            <div>
              <strong>{driverLabel(f.subject_driver_id, f.drivers)}</strong>
              <span className="finding-location">
                {f.finding_type.replace(/_/g, " ")} · {COMPARED_AGAINST_LABEL[f.compared_against_type] ?? f.compared_against_type}
              </span>
            </div>
            <div className="finding-badges">
              <SeverityBadge severity={f.severity}>{f.severity}</SeverityBadge>
            </div>
          </div>
          <p>{f.message}</p>
        </div>
      ))}
    </div>
  );
}

export default InsightsTab;
