import { useMemo } from "react";
import { nearestAt } from "../../utils/telemetry";
import { detectCorners, detectBrakingPoints } from "../../utils/trackGeometry";

const PADDING = 20;
const VIEW_SIZE = 400;

// Circuit dimensions vary wildly (Monaco vs Spa), so the viewBox is derived
// from each lap's own bounding box rather than a fixed size -- a single
// scale factor for both axes (not independently stretched width/height) is
// what keeps every corner's real shape instead of visually distorting it.
function buildPath(series) {
  if (!series.length) return null;

  const xs = series.map((p) => p.x).filter((v) => v !== null);
  const ys = series.map((p) => p.y).filter((v) => v !== null);
  if (!xs.length || !ys.length) return null;

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const drawable = VIEW_SIZE - PADDING * 2;
  const scale = drawable / Math.max(spanX, spanY);
  // A single scale factor means one axis fills the drawable area exactly
  // and the other comes up short (a track is rarely square) -- center that
  // shorter axis instead of anchoring it to the top/left, or a tall-narrow
  // track like Monaco renders squeezed into one corner.
  const offsetX = PADDING + (drawable - spanX * scale) / 2;
  const offsetY = PADDING + (drawable - spanY * scale) / 2;

  // FastF1's position data is a flat car-relative plane, not screen space --
  // Y is flipped here so the map reads top-down the way a track guide would
  // rather than mirrored; unverified against a real ingested lap yet (no
  // session exists in the live DB at the time this was written), worth a
  // sanity check the first time a real lap renders oddly.
  const toScreen = (p) => ({
    sx: offsetX + (p.x - minX) * scale,
    sy: offsetY + (spanY * scale) - (p.y - minY) * scale,
  });

  const points = series
    .filter((p) => p.x !== null && p.y !== null)
    .map(toScreen);

  return { points, toScreen };
}

// series/seriesB: buildLapPositionSeries output for one (or two, in
// compareMode) laps. telemetrySeries/telemetrySeriesB: buildLapTelemetrySeries
// output for the SAME laps -- optional, only used to derive braking-point
// markers (already fetched by TelemetryTab/CompareTab for the channel
// panels above this, so no new query here). hoverTimeS: lifted from the
// parent so the cursor marker tracks the same scrub position as the synced
// channel panels -- this component isn't a Recharts chart, so syncId can't
// reach it.
function TrackMapPanel({ series, hoverTimeS, seriesB = null, telemetrySeries = null, telemetrySeriesB = null }) {
  const path = useMemo(() => buildPath(series), [series]);
  const pathB = useMemo(() => (seriesB ? buildPath(seriesB) : null), [seriesB]);
  const corners = useMemo(() => detectCorners(series), [series]);
  const brakingPoints = useMemo(
    () => (telemetrySeries ? detectBrakingPoints(telemetrySeries, series) : []),
    [telemetrySeries, series]
  );
  const brakingPointsB = useMemo(
    () => (telemetrySeriesB && seriesB ? detectBrakingPoints(telemetrySeriesB, seriesB) : []),
    [telemetrySeriesB, seriesB]
  );

  if (!path) {
    return (
      <div className="track-map-shell">
        <p style={{ color: "var(--muted)", fontSize: 13 }}>No position data recorded for this lap.</p>
      </div>
    );
  }

  const cursor = hoverTimeS !== null ? path.toScreen(nearestAt(series, hoverTimeS)) : null;
  const cursorB = pathB && hoverTimeS !== null ? pathB.toScreen(nearestAt(seriesB, hoverTimeS)) : null;

  return (
    <div className="track-map-shell">
      <svg viewBox={`0 0 ${VIEW_SIZE} ${VIEW_SIZE}`} preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
        <polyline
          points={path.points.map((p) => `${p.sx},${p.sy}`).join(" ")}
          fill="none"
          stroke="var(--blue-bright)"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        {pathB && (
          <polyline
            points={pathB.points.map((p) => `${p.sx},${p.sy}`).join(" ")}
            fill="none"
            stroke="var(--amber)"
            strokeWidth={2}
            strokeLinejoin="round"
          />
        )}

        {corners.map((c) => {
          const p = path.toScreen(c);
          return (
            <g key={c.number} className="track-corner-marker">
              <circle cx={p.sx} cy={p.sy} r={7} />
              <text x={p.sx} y={p.sy}>{c.number}</text>
            </g>
          );
        })}

        {brakingPoints.map((bp, i) => {
          const p = path.toScreen(bp);
          return <circle key={i} className="track-braking-marker" cx={p.sx} cy={p.sy} r={3} fill="var(--blue-bright)" />;
        })}
        {pathB && brakingPointsB.map((bp, i) => {
          const p = pathB.toScreen(bp);
          return <circle key={i} className="track-braking-marker" cx={p.sx} cy={p.sy} r={3} fill="var(--amber)" />;
        })}

        {cursor && (
          <>
            <circle
              className="pulse-glow"
              cx={cursor.sx}
              cy={cursor.sy}
              r={10}
              fill="var(--blue-bright)"
              opacity={0.35}
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
            />
            <circle cx={cursor.sx} cy={cursor.sy} r={5} fill="var(--blue-bright)" stroke="#fff" strokeWidth={1.5} />
          </>
        )}
        {cursorB && (
          <>
            <circle
              className="pulse-glow"
              cx={cursorB.sx}
              cy={cursorB.sy}
              r={10}
              fill="var(--amber)"
              opacity={0.35}
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
            />
            <circle cx={cursorB.sx} cy={cursorB.sy} r={5} fill="var(--amber)" stroke="#fff" strokeWidth={1.5} />
          </>
        )}
      </svg>
    </div>
  );
}

export default TrackMapPanel;
