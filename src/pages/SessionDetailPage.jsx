import { useState } from "react";
import { getSession } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import ResultsTab from "./session-tabs/ResultsTab";
import LapsTab from "./session-tabs/LapsTab";
import TelemetryTab from "./session-tabs/TelemetryTab";
import CompareTab from "./session-tabs/CompareTab";
import SetupTab from "./session-tabs/SetupTab";
import InsightsTab from "./session-tabs/InsightsTab";
import StrategyTab from "./session-tabs/StrategyTab";

const TABS = ["Results", "Laps", "Telemetry", "Compare", "Setup", "Strategy", "Insights"];

function SessionDetailPage({ sessionId, onBack }) {
  const { status, data: session } = useAsync(() => getSession(sessionId), [sessionId]);
  const [tab, setTab] = useState("Results");
  const [selectedLap, setSelectedLap] = useState(null); // { lapId, driverId, lapNumber }

  function viewTelemetry(lapId, driverId, lapNumber) {
    setSelectedLap({ lapId, driverId, lapNumber });
    setTab("Telemetry");
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <p className="eyebrow">
            <button className="secondary-button" onClick={onBack}>
              ← Sessions
            </button>
            {status === "success" && `${session.season} Round ${session.round_number}`}
          </p>
          <h2>{status === "success" ? `${session.event_name} — ${session.session_name}` : "Loading…"}</h2>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Results" && <ResultsTab sessionId={sessionId} />}
      {tab === "Laps" && <LapsTab sessionId={sessionId} onViewTelemetry={viewTelemetry} />}
      {tab === "Telemetry" && (
        <TelemetryTab
          sessionId={sessionId}
          lapId={selectedLap?.lapId ?? null}
          driverId={selectedLap?.driverId ?? null}
          lapNumber={selectedLap?.lapNumber ?? null}
        />
      )}
      {tab === "Compare" && <CompareTab sessionId={sessionId} />}
      {tab === "Setup" && <SetupTab sessionId={sessionId} />}
      {tab === "Strategy" && <StrategyTab sessionId={sessionId} />}
      {tab === "Insights" && <InsightsTab sessionId={sessionId} />}
    </section>
  );
}

export default SessionDetailPage;
