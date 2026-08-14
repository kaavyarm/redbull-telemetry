import { listSessions } from "../lib/api";
import { useAsync } from "../hooks/useAsync";

function groupByWeekend(sessions) {
  const groups = new Map();
  for (const s of sessions) {
    const key = `${s.season}-${s.round_number}`;
    if (!groups.has(key)) {
      groups.set(key, { event_name: s.event_name, location: s.location, country: s.country, sessions: [] });
    }
    groups.get(key).sessions.push(s);
  }
  return [...groups.values()];
}

const SESSION_TYPE_LABELS = {
  practice_1: "FP1",
  practice_2: "FP2",
  practice_3: "FP3",
  sprint_qualifying: "Sprint Qualifying",
  sprint: "Sprint",
  qualifying: "Qualifying",
  race: "Race",
};

function SessionsPage({ onSelectSession }) {
  const { status, data: sessions, error } = useAsync(() => listSessions(), []);

  return (
    <section>
      <div className="page-header">
        <div>
          <p className="eyebrow">Sessions</p>
          <h2>Session Explorer</h2>
        </div>
      </div>

      {status === "loading" && (
        <div className="section-card">
          <h3>Loading…</h3>
        </div>
      )}

      {status === "error" && (
        <div className="section-card">
          <h3>Couldn't load sessions</h3>
          <p>{error.message}</p>
        </div>
      )}

      {status === "success" && sessions.length === 0 && (
        <div className="section-card">
          <h3>No sessions ingested yet</h3>
          <p>Run scripts/ingest_weekend.py for a race weekend to see it here.</p>
        </div>
      )}

      {status === "success" && sessions.length > 0 && (
        <div className="record-list">
          {groupByWeekend(sessions).map((weekend) => (
            <div key={weekend.event_name} className="record-card" style={{ cursor: "default" }}>
              <div className="record-topline">
                <span>{weekend.location}, {weekend.country}</span>
              </div>
              <h3>{weekend.event_name}</h3>
              <div className="chip-row">
                {weekend.sessions.map((s) => (
                  <button key={s.id} className="chip" onClick={() => onSelectSession(s.id)}>
                    {SESSION_TYPE_LABELS[s.session_type] || s.session_type}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default SessionsPage;
