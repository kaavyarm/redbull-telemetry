import { useEffect, useState } from "react";

// A media query preference, not per-instance state -- computed once at
// module load rather than read from a ref during render.
const prefersReducedMotion =
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

const STROKE_WIDTH = 8;

const TONE_COLOR = {
  cyan: "var(--cyan)",
  green: "var(--green)",
  amber: "var(--amber)",
  blood: "var(--blood-bright)",
};

const TONE_GLOW = {
  cyan: "var(--cyan-glow)",
  green: "rgba(81, 224, 127, 0.35)",
  amber: "rgba(200, 145, 50, 0.35)",
  blood: "rgba(139, 14, 31, 0.4)",
};

// Hand-rolled SVG gauge, same construction pattern as TrackMapPanel.jsx
// (sized viewBox, stroke-based drawing) rather than Recharts' RadialBarChart
// -- full control over the glow filter and the fill animation below, which
// Recharts' chart-oriented radial component isn't built for.
function RadialGauge({ value, min = 0, max = 100, label, unit = "", tone = "cyan", size = 120, formatValue }) {
  const radius = (size - STROKE_WIDTH) / 2;
  const circumference = 2 * Math.PI * radius;

  const hasValue = value !== null && value !== undefined && !Number.isNaN(Number(value));
  const clamped = hasValue ? Math.max(min, Math.min(max, Number(value))) : min;
  const pct = max === min ? 0 : (clamped - min) / (max - min);

  // Starts at 0 (the useState initializer) and only ever moves via the RAF
  // callback below -- under reduced motion, the render derives straight
  // from `pct` instead, so this state is simply never touched in that case.
  const [animatedPct, setAnimatedPct] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion) return;
    // One frame after mount/update so the CSS `transition` below has
    // something to animate from -> to, rather than snapping instantly.
    const raf = requestAnimationFrame(() => setAnimatedPct(pct));
    return () => cancelAnimationFrame(raf);
  }, [pct]);

  const effectivePct = prefersReducedMotion ? pct : animatedPct;
  const offset = circumference * (1 - effectivePct);
  const color = TONE_COLOR[tone] ?? TONE_COLOR.cyan;
  const glow = TONE_GLOW[tone] ?? TONE_GLOW.cyan;
  const display = hasValue ? (formatValue ? formatValue(Number(value)) : Number(value).toFixed(2)) : "N/A";

  return (
    <div className="radial-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border-soft)"
          strokeWidth={STROKE_WIDTH}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={STROKE_WIDTH}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{
            transition: prefersReducedMotion ? "none" : "stroke-dashoffset 900ms cubic-bezier(0.16, 1, 0.3, 1)",
            filter: `drop-shadow(0 0 6px ${glow})`,
          }}
        />
      </svg>
      <div className="radial-gauge-readout">
        <strong>
          {display}
          {hasValue && unit}
        </strong>
        {label && <span>{label}</span>}
      </div>
    </div>
  );
}

export default RadialGauge;
