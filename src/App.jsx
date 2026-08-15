import { useState } from "react";
import AuthGate from "./components/AuthGate";
import Sidebar from "./components/Sidebar";
import ErrorFallback from "./components/ErrorFallback";
import OverviewPage from "./pages/OverviewPage";
import SessionsPage from "./pages/SessionsPage";
import SessionDetailPage from "./pages/SessionDetailPage";
import { Sentry } from "./lib/sentry";
import "./styles/variables.css";
import "./styles/layout.css";
import "./styles/shared.css";
import "./styles/telemetry.css";
import "./styles/motion.css";

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [selectedSessionId, setSelectedSessionId] = useState(null);

  function goToPage(page) {
    setSelectedSessionId(null);
    setActivePage(page);
  }

  return (
    <AuthGate>
      {(session) => (
        <div className="app">
          <Sidebar activePage={activePage} setActivePage={goToPage} userEmail={session.user.email} />

          <main className="main">
            {/* Scoped to page content, not the whole app -- the sidebar
                stays usable so a crash on one page doesn't strand the user;
                they can navigate elsewhere. key= forces a fresh boundary
                (and remount) on navigation so a stale error doesn't linger
                after moving to a different page. */}
            <Sentry.ErrorBoundary
              key={`${activePage}-${selectedSessionId ?? "list"}`}
              fallback={ErrorFallback}
            >
              {activePage === "Overview" && <OverviewPage />}
              {activePage === "Sessions" && selectedSessionId === null && (
                <SessionsPage onSelectSession={setSelectedSessionId} />
              )}
              {activePage === "Sessions" && selectedSessionId !== null && (
                <SessionDetailPage
                  sessionId={selectedSessionId}
                  onBack={() => setSelectedSessionId(null)}
                />
              )}
            </Sentry.ErrorBoundary>
          </main>
        </div>
      )}
    </AuthGate>
  );
}

export default App;
