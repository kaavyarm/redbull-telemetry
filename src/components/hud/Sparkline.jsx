// Tiny inline trend line -- no axes, no labels, just the shape. Meant to
// sit inside a dense table cell (e.g. a stint's lap-by-lap pace) where a
// full Recharts panel would be overkill; same "hand-roll it" precedent as
// RadialGauge/AnimatedNumber, not a charting-library job.
function Sparkline({ values, width = 72, height = 22, color = "var(--cyan)" }) {
  const valid = (values || []).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  if (valid.length < 2) {
    return <span className="sparkline-empty">—</span>;
  }

  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const span = max - min || 1;
  const points = valid
    .map((v, i) => {
      const x = (i / (valid.length - 1)) * width;
      const y = height - ((v - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="sparkline">
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export default Sparkline;
