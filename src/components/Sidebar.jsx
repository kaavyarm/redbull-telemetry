import { useMemo, useState } from "react";
import { signOut, listSessions, getFindingsSeverityBySession } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { sessionTypeLabel, severityRank } from "../utils/format";

const NAV_PAGES = ["Overview", "Sessions", "Trends"];

function groupBySeasonAndWeekend(sessions) {
  const seasons = new Map();
  for (const s of sessions) {
    if (!seasons.has(s.season)) seasons.set(s.season, new Map());
    const weekends = seasons.get(s.season);
    const key = `${s.season}-${s.round_number}`;
    if (!weekends.has(key)) {
      weekends.set(key, { key, event_name: s.event_name, sessions: [] });
    }
    weekends.get(key).sessions.push(s);
  }
  return [...seasons.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([season, weekends]) => ({ season, weekends: [...weekends.values()] }));
}

// The tree only needs to know the single worst severity per session, not
// each finding's detail -- getFindingsSeverityBySession() gives exactly
// that (session_id + severity, every session the owner can see), reduced
// here with the same severityRank() every other severity comparison in
// this app already uses.
function maxSeverityBySession(rows) {
  const map = new Map();
  for (const row of rows || []) {
    const current = map.get(row.session_id);
    if (!current || severityRank(row.severity) > severityRank(current)) {
      map.set(row.session_id, row.severity);
    }
  }
  return map;
}

function Sidebar({ activePage, setActivePage, selectedSessionId, onSelectSession, onOpenPalette, userEmail, open = false }) {
  const { data: sessions } = useAsync(() => listSessions(), []);
  const { data: severityRows } = useAsync(() => getFindingsSeverityBySession(), []);
  const [expanded, setExpanded] = useState(() => new Set());

  const tree = useMemo(() => groupBySeasonAndWeekend(sessions || []), [sessions]);
  const severityBySession = useMemo(() => maxSeverityBySession(severityRows), [severityRows]);

  // Auto-expand whichever weekend contains the session currently open, so
  // jumping in from the command palette (or a fresh load with a session
  // already selected) never leaves you looking at a collapsed tree.
  const activeWeekendKey = useMemo(() => {
    if (!selectedSessionId || !sessions) return null;
    const active = sessions.find((s) => s.id === selectedSessionId);
    return active ? `${active.season}-${active.round_number}` : null;
  }, [sessions, selectedSessionId]);

  function isExpanded(key) {
    return expanded.has(key) || key === activeWeekendKey;
  }

  function toggleWeekend(key) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <aside className={open ? "sidebar open" : "sidebar"}>
      <div className="brand">
        <div className="brand-mark">RB</div>
        <div>
          <h1>Red Bull Telemetry</h1>
          <p>2026 Season</p>
        </div>
      </div>

      {/* Reflects a real state (AuthGate only renders this component once a
          Supabase auth session exists) -- not a decorative claim. */}
      <div className="system-status">
        <span className="system-status-dot pulse-glow" />
        <span>Session active</span>
      </div>

      <nav className="nav">
        {NAV_PAGES.map((page) => (
          <button
            key={page}
            className={activePage === page ? "nav-item active" : "nav-item"}
            onClick={() => setActivePage(page)}
          >
            {page}
          </button>
        ))}
      </nav>

      <button className="palette-trigger" onClick={onOpenPalette}>
        <span>Search sessions</span>
        <kbd>⌘K</kbd>
      </button>

      <div className="session-tree">
        {tree.map(({ season, weekends }) => (
          <div key={season} className="tree-season">
            <p className="tree-season-label">{season} season</p>
            {weekends.map((weekend) => {
              const open = isExpanded(weekend.key);
              return (
                <div key={weekend.key} className="tree-weekend">
                  <button className="tree-weekend-toggle" onClick={() => toggleWeekend(weekend.key)}>
                    <span className={open ? "tree-caret open" : "tree-caret"}>▸</span>
                    {weekend.event_name}
                  </button>
                  {open && (
                    <div className="tree-sessions">
                      {weekend.sessions.map((s) => {
                        const severity = severityBySession.get(s.id);
                        const flagged = severity === "high" || severity === "medium";
                        return (
                          <button
                            key={s.id}
                            className={s.id === selectedSessionId ? "tree-session active" : "tree-session"}
                            onClick={() => onSelectSession(s.id)}
                          >
                            <span>{sessionTypeLabel(s.session_type)}</span>
                            {flagged && <span className={`tree-dot ${severity}`} />}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="sidebar-account">
        <p className="sidebar-account-email">{userEmail}</p>
        <button className="secondary-button sidebar-sign-out" onClick={() => signOut()}>
          Sign out
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
