import { useEffect, useRef, useState } from "react";

// A media query preference, not per-instance state -- computed once at
// module load rather than read from a ref during render (which React 19's
// stricter hook rules flag even for values that never change).
const prefersReducedMotion =
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// Counts from the previously rendered numeric value to a new one --
// requestAnimationFrame + ease-out cubic, no animation library. The first
// time a real number arrives (whether that's on mount or after a loading
// state resolves) it always counts up from 0, so a stat card reads as the
// system tallying rather than just appearing. Skips straight to the target
// under prefers-reduced-motion, and passes non-numeric values
// (null/undefined/"N/A") through to `format` untouched.
//
// Only the requestAnimationFrame callback calls setState -- every other
// case (no value yet, reduced motion, value unchanged) is derived directly
// during render instead, since setState called synchronously in an effect
// body (rather than from an async callback) triggers cascading re-renders.
function AnimatedNumber({ value, format = (v) => v, duration = 700 }) {
  const isValidNumber = value !== null && value !== undefined && !Number.isNaN(Number(value));
  const numericValue = isValidNumber ? Number(value) : null;

  const [animatedValue, setAnimatedValue] = useState(0);
  const fromRef = useRef(null);

  useEffect(() => {
    if (numericValue === null || prefersReducedMotion) {
      return;
    }
    const from = typeof fromRef.current === "number" ? fromRef.current : 0;
    const to = numericValue;
    if (from === to) {
      fromRef.current = to;
      return;
    }

    let raf;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      setAnimatedValue(from + (to - from) * eased);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [numericValue, duration]);

  const display = numericValue === null ? value : prefersReducedMotion ? numericValue : animatedValue;
  return <>{format(display)}</>;
}

export default AnimatedNumber;
