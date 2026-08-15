import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { listSessions, getSessionResults, getDerivedMetrics } from "../lib/api";
import { useAsync } from "../hooks/useAsync";

const RED_BULL_TEAM_ID = "red_bull";

// Round-over-round view, scoped to race sessions specifically -- the
// clearest single unit for a season trend (mixing FP/Quali/Race scales
// would just be noise). One compound async fetch per useAsync's existing
// convention (CompareTab already does the same "await one thing, then
// Promise.all a batch of follow-ups" shape), not a new data-fetching
// pattern -- a client-side loop rather than a new backend aggregate
// endpoint, since this stays cheap at the handful of rounds ingested so far.
async function loadSeasonTrends() {
  const sessions = await listSessions();
  const races = sessions
    .filter((s) => s.session_type === "race")
    .sort((a, b) => a.round_number - b.round_number);

  return Promise.all(
    races.map(async (race) => {
      const [results, degradationRows] = await Promise.all([
        getSessionResults(race.id),
        getDerivedMetrics(race.id, "stint_degradation"),
      ]);
      const rbResults = results.filter((r) => r.team_id === RED_BULL_TEAM_ID);
      const rbDriverIds = new Set(rbResults.map((r) => r.driver_id));

      const positions = rbResults.map((r) => r.position).filter((p) => p !== null);
      const avgPosition = positions.length ? positions.reduce((a, b) => a + b, 0) / positions.length : null;
      const totalPoints = rbResults.reduce((sum, r) => sum + (Number(r.points) || 0), 0);

      const rbDegradation = degradationRows.filter(
        (d) => rbDriverIds.has(d.driver_id) && (d.value?.confidence === "medium" || d.value?.confidence === "high")
      );
      const avgDegradation = rbDegradation.length
        ? rbDegradation.reduce((sum, d) => sum + d.value.slope_s_per_lap, 0) / rbDegradation.length
        : null;

      return {
        round: race.round_number,
        eventName: race.event_name,
        avgPosition,
        totalPoints,
        avgDegradation,
      };
    })
  );
}

function TrendsPage() {
  const { status, data: trends, error } = useAsync(() => loadSeasonTrends(), []);

  return (
    <section>
      <div className="page-header">
        <div>
          <p className="eyebrow">Trends</p>
          <h2>Season — Race Performance</h2>
        </div>
      </div>

      {status === "loading" && <div className="section-card"><h3>Loading…</h3></div>}
      {status === "error" && (
        <div className="section-card"><h3>Couldn't load season trends</h3><p>{error.message}</p></div>
      )}
      {status === "success" && trends.length === 0 && (
        <div className="section-card">
          <h3>No race sessions ingested yet</h3>
          <p>This page fills in once at least one race weekend has been ingested.</p>
        </div>
      )}

      {status === "success" && trends.length > 0 && (
        <div className="stack">
          <div className="section-card">
            <div className="chart-header">
              <div>
                <h3>Finishing position &amp; points</h3>
                <span>{trends.length} race{trends.length === 1 ? "" : "s"} ingested so far this season.</span>
              </div>
            </div>
            <div className="chart-shell">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trends}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="round" stroke="var(--muted)" fontSize={11} label={{ value: "Round", position: "insideBottom", offset: -4, fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis yAxisId="position" stroke="var(--muted)" fontSize={11} reversed domain={["auto", "auto"]} />
                  <YAxis yAxisId="points" orientation="right" stroke="var(--muted)" fontSize={11} domain={[0, "auto"]} />
                  <Tooltip contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }} />
                  <Line yAxisId="position" type="monotone" dataKey="avgPosition" name="Avg finishing position" stroke="var(--blood-bright)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                  <Line yAxisId="points" type="monotone" dataKey="totalPoints" name="Points scored" stroke="var(--cyan)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="section-card">
            <div className="chart-header">
              <div>
                <h3>Tire degradation trend</h3>
                <span>Red Bull's average stint degradation (medium/high-confidence stints only) per round.</span>
              </div>
            </div>
            <div className="chart-shell">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trends}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="round" stroke="var(--muted)" fontSize={11} label={{ value: "Round", position: "insideBottom", offset: -4, fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis stroke="var(--muted)" fontSize={11} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }}
                    formatter={(value) => (value === null ? "N/A" : `${Number(value).toFixed(3)} s/lap`)}
                  />
                  <Line type="monotone" dataKey="avgDegradation" name="Avg degradation (s/lap)" stroke="var(--amber)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="strategy-note">
              Rounds without a value here haven't had the analytics/insights batch job run yet
              (scripts/compute_derived_metrics.py) -- the race results above still reflect real data either way.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

export default TrendsPage;
