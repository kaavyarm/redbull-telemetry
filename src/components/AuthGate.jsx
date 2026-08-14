import { useEffect, useState } from "react";
import { getCurrentSession, onAuthStateChange, signInWithPassword } from "../lib/api";

// RLS grants `authenticated` read access to nothing until a Supabase auth
// session exists (see supabase/schema.sql) -- there's no anonymous read
// path at all for a single-user project like this one, so every screen
// behind this gate would otherwise just render empty. Sign-in only, no
// sign-up: the one dashboard user's account is created once via the
// Supabase dashboard, matching SUPABASE_OWNER_USER_ID from the ingestion
// pipeline (see .env.example).
function AuthGate({ children }) {
  const [session, setSession] = useState(undefined); // undefined = still checking
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getCurrentSession().then(({ data }) => setSession(data.session));
    const subscription = onAuthStateChange((next) => setSession(next));
    return () => subscription.unsubscribe();
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signInWithPassword(email, password);
    } catch (err) {
      setError(err.message || "Sign-in failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (session === undefined) {
    return null; // avoid a login-form flash while the existing session loads
  }

  if (!session) {
    return (
      <div className="auth-screen">
        <form className="auth-card" onSubmit={handleSubmit}>
          <div className="brand">
            <div className="brand-mark">RB</div>
            <div>
              <h1>Red Bull Telemetry</h1>
              <p>2026 Season</p>
            </div>
          </div>
          <label className="auth-field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return children(session);
}

export default AuthGate;
