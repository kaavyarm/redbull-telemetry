import { signOut } from "../lib/api";

const NAV_PAGES = ["Overview", "Sessions"];

function Sidebar({ activePage, setActivePage, userEmail }) {
  return (
    <aside className="sidebar">
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
