import { listSessions } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import StatusCard from "../components/StatusCard";

function summarize(sessions) {
  const weekends = new Set(sessions.map((s) => `${s.season}-${s.round_number}`));
  const races = sessions.filter((s) => s.session_type === "race");
  const latest = sessions[0]; // listSessions() orders newest first
  return { weekendCount: weekends.size, sessionCount: sessions.length, raceCount: races.length, latest };
}

function OverviewPage() {
  const { status, data: sessions, error } = useAsync(() => listSessions(), []);

  return (
    <section>
      <div className="page-header">
        <div>
          <p className="eyebrow">Overview</p>
          <h2>Red Bull — 2026 Season</h2>
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
          <h3>No data yet</h3>
          <p>
            This page will show the season so far once a weekend has been
            ingested (scripts/ingest_weekend.py). Nothing here is placeholder
            numbers standing in for real ones — it&apos;s empty until
            there&apos;s something real to show.
          </p>
        </div>
      )}

      {status === "success" && sessions.length > 0 && (
        <>
          <div className="detail-grid">
            <StatusCard label="Weekends ingested" value={summarize(sessions).weekendCount} detail="race weekends" />
            <StatusCard label="Sessions ingested" value={summarize(sessions).sessionCount} detail="practice, qualifying, race" />
            <StatusCard label="Race sessions" value={summarize(sessions).raceCount} detail="full races" />
            <StatusCard
              label="Most recent"
              value={summarize(sessions).latest.event_name}
              detail={summarize(sessions).latest.session_name}
            />
          </div>
          <div className="section-card">
            <h3>Ingested weekends</h3>
            <p>
              {[...new Set(sessions.map((s) => s.event_name))].join(" · ")}
            </p>
          </div>
        </>
      )}
    </section>
  );
}

export default OverviewPage;
