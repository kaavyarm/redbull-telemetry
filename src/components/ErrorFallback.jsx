// Fallback UI for Sentry.ErrorBoundary (wired in App.jsx). Without this,
// an unhandled render error takes the whole app to a blank screen with no
// way back short of a manual reload. Scoped so the sidebar/nav stays
// usable and the user gets a real message instead of staring at black.
function ErrorFallback({ error, resetError }) {
  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="brand">
          <div className="brand-mark">RB</div>
          <div>
            <h1>Something broke</h1>
            <p>Red Bull Telemetry</p>
          </div>
        </div>
        <p style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.5 }}>
          {error?.message || "An unexpected error occurred."}
        </p>
        <button className="primary-button" onClick={resetError}>
          Try again
        </button>
      </div>
    </div>
  );
}

export default ErrorFallback;
