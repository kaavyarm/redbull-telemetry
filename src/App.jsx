import { useEffect, useState } from "react";
import AuthGate from "./components/AuthGate";
import Sidebar from "./components/Sidebar";
import CommandPalette from "./components/CommandPalette";
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
  const [paletteOpen, setPaletteOpen] = useState(false);

  function goToPage(page) {
    setSelectedSessionId(null);
    setActivePage(page);
  }

  // The one place that sets both pieces of routing state together -- used
  // by the sidebar's session tree and the command palette, neither of
  // which should have to know that "viewing a session" also means
  // activePage === "Sessions" under the hood.
  function goToSession(sessionId) {
    setActivePage("Sessions");
    setSelectedSessionId(sessionId);
    setPaletteOpen(false);
  }

  useEffect(() => {
    function onKeyDown(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      } else if (event.key === "Escape") {
        setPaletteOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <AuthGate>
      {(session) => (
        <div className="app">
          <Sidebar
            activePage={activePage}
            setActivePage={goToPage}
            selectedSessionId={selectedSessionId}
            onSelectSession={goToSession}
            onOpenPalette={() => setPaletteOpen(true)}
            userEmail={session.user.email}
          />

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
                <SessionsPage onSelectSession={goToSession} />
              )}
              {activePage === "Sessions" && selectedSessionId !== null && (
                <SessionDetailPage
                  sessionId={selectedSessionId}
                  onBack={() => setSelectedSessionId(null)}
                />
              )}
            </Sentry.ErrorBoundary>
          </main>

          {paletteOpen && (
            <CommandPalette onSelectSession={goToSession} onClose={() => setPaletteOpen(false)} />
          )}
        </div>
      )}
    </AuthGate>
  );
}

export default App;
