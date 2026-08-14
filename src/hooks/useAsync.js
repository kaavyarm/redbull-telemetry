import { useEffect, useState } from "react";

// Every page in this app fetches from Supabase the same way (loading ->
// data or error), so that state machine lives here once instead of five
// times. `deps` re-runs the fetch when any of them change (e.g. a new
// sessionId).
//
// The synchronous setState at the top of the effect (reset to "loading"
// before the async call starts) is the pattern React's own docs show for
// this exact case -- https://react.dev/learn/you-might-not-need-an-effect
// -- and eslint-plugin-react-hooks' newer set-state-in-effect rule flags it
// anyway. A render-time-adjustment rewrite (comparing deps via a ref, per
// that same doc's "adjusting state when a prop changes" section) was tried
// and hits a *different* rule in this same plugin version
// (react-hooks/refs, "cannot access refs during render") on the exact
// pattern the docs describe -- these two rules currently disagree with
// each other on this case. Disabling the narrower one here rather than
// restructuring around a moving target.
export function useAsync(fn, deps) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ status: "loading", data: null, error: null });

    fn()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data, error: null });
      })
      .catch((error) => {
        if (!cancelled) setState({ status: "error", data: null, error });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
