import * as Sentry from "@sentry/react";

// No-op when VITE_SENTRY_DSN isn't set -- this is a personal project, not
// every environment running it has (or needs) a Sentry account, and the
// app must render normally either way.
export function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return false;

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || "development",
    tracesSampleRate: 0.1,
    integrations: [Sentry.browserTracingIntegration()],
  });
  return true;
}

export { Sentry };
