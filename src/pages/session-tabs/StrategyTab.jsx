import { useMemo, useState } from "react";
import { getSessionResults, getStintPerformance, getDerivedMetrics, getLaps } from "../../lib/api";
import { useAsync } from "../../hooks/useAsync";
import { computeCleanMedianPace, computeRealPitLoss, simulateAlternatePitLap } from "../../utils/strategy";
import { formatDelta } from "../../utils/format";
import AnimatedNumber from "../../components/hud/AnimatedNumber";

const RED_BULL_TEAM_ID = "red_bull";
const LOW_CONFIDENCE = new Set(["insufficient_data", "low"]);

// Picks the first (driver, pit-stop) pair, scanning ONLY Red Bull drivers
// (never falling through to the rest of the field -- an earlier version of
// this did, and defaulted a Red Bull strategy tool to Fernando Alonso the
// moment neither Red Bull driver had a clean-confidence pair), whose stints
// on both sides both have usable degradation confidence, so the tab opens
// on a working example instead of the "insufficient data" warning. Falls
// back to the first Red Bull driver's first pit stop (the original
// unconditional default) if no Red Bull combination has good data -- the
// honest warning is still correct to show when that's genuinely the case.
function computeDefaultSelection(results, stints, degradationByStint) {
  if (!results?.length || !stints?.length) return null;
  const rbDrivers = results.filter((r) => r.team_id === RED_BULL_TEAM_ID);
  let fallback = null;
  for (const r of rbDrivers) {
    const driverStints = stints
      .filter((s) => s.driver_id === r.driver_id)
      .sort((a, b) => a.stint_number - b.stint_number);
    for (let i = 0; i < driverStints.length - 1; i++) {
      const stintA = driverStints[i];
      const stintB = driverStints[i + 1];
      if (!fallback) fallback = { driverId: r.driver_id, transitionIndex: i };
      const degA = degradationByStint.get(`${r.driver_id}-${stintA.stint_number}`);
      const degB = degradationByStint.get(`${r.driver_id}-${stintB.stint_number}`);
      // A missing row (degradation never computed for a too-short stint)
      // is just as unusable as an explicit low-confidence one -- treating
      // "missing" as "fine" here previously picked stint pairs that could
      // never actually simulate, landing on the same "not enough data"
      // message the smart default was meant to avoid.
      const usable = (deg) => deg && !LOW_CONFIDENCE.has(deg.confidence);
      if (usable(degA) && usable(degB)) {
        return { driverId: r.driver_id, transitionIndex: i };
      }
    }
  }
  // Neither Red Bull driver has even one pit-stop transition (e.g. both
  // retired on lap 1) -- still default to a Red Bull driver rather than
  // leaving the picker empty; the existing "not enough stints" state
  // handles the rest.
  return fallback ?? (rbDrivers[0] ? { driverId: rbDrivers[0].driver_id, transitionIndex: 0 } : null);
}

// "What if we'd pitted lap N instead" -- projects lap times outside the
// laps actually run in each stint using that stint's own fitted
// degradation trend (src/utils/strategy.js), and compares the projected
// total to what actually happened over the same lap range. Every number
// here is a projection, not a measurement -- the UI leans on that framing
// rather than presenting a false-precision "you lost 2.3s" claim.
function StrategyTab({ sessionId }) {
  const { status: resultsStatus, data: results, error: resultsError } = useAsync(
    () => getSessionResults(sessionId),
    [sessionId]
  );
  const { status: stintStatus, data: stints } = useAsync(() => getStintPerformance(sessionId), [sessionId]);
  const { data: degradationRows } = useAsync(
    () => getDerivedMetrics(sessionId, "stint_degradation"),
    [sessionId]
  );

  const degradationByStint = useMemo(() => {
    const map = new Map();
    for (const row of degradationRows || []) {
      map.set(`${row.driver_id}-${row.subject?.stint_number}`, row.value);
    }
    return map;
  }, [degradationRows]);

  // Plain call, not useMemo -- a cheap scan (a couple of drivers x a
  // handful of stints each), and chaining useMemo off degradationByStint
  // (itself derived) is exactly what trips React Compiler's
  // preserve-manual-memoization check, same as the other derived values
  // below.
  const defaultSelection = computeDefaultSelection(results, stints, degradationByStint);

  const [driverId, setDriverId] = useState(null);
  const effectiveDriverId = driverId ?? defaultSelection?.driverId ?? null;

  const { data: laps } = useAsync(
    () => (effectiveDriverId ? getLaps(sessionId, effectiveDriverId) : Promise.resolve([])),
    [sessionId, effectiveDriverId]
  );

  const driverStints = useMemo(
    () => (stints || []).filter((s) => s.driver_id === effectiveDriverId).sort((a, b) => a.stint_number - b.stint_number),
    [stints, effectiveDriverId]
  );

  const transitions = driverStints.slice(0, -1).map((stintA, i) => ({ stintA, stintB: driverStints[i + 1] }));
  const [transitionIndex, setTransitionIndex] = useState(null);
  const effectiveTransitionIndex = transitionIndex ?? defaultSelection?.transitionIndex ?? 0;
  const transition = transitions[Math.min(effectiveTransitionIndex, transitions.length - 1)] ?? null;

  // Plain derived values, not useMemo -- these are cheap scans over a
  // single stint's worth of laps (tens of rows at most), not expensive
  // enough to need memoizing, and chaining useMemo off other non-memoized
  // derived values is exactly what trips up React Compiler's
  // preserve-manual-memoization check.
  const cleanMedianS = computeCleanMedianPace(laps || []);
  const actualPitLap = transition?.stintA.lap_end ?? null;
  const pitLossS = actualPitLap !== null ? computeRealPitLoss(laps || [], actualPitLap, cleanMedianS) : null;

  const [candidateLap, setCandidateLap] = useState(null);
  const effectiveCandidateLap = candidateLap ?? actualPitLap;

  const degA = transition && degradationByStint.get(`${effectiveDriverId}-${transition.stintA.stint_number}`);
  const degB = transition && degradationByStint.get(`${effectiveDriverId}-${transition.stintB.stint_number}`);

  const simulation =
    transition && degA && degB && actualPitLap !== null && effectiveCandidateLap !== null
      ? simulateAlternatePitLap({
          stintA: {
            lapStart: transition.stintA.lap_start,
            interceptS: degA.intercept_s,
            slopeSPerLap: degA.slope_s_per_lap,
            confidence: degA.confidence,
          },
          stintB: {
            lapStart: transition.stintB.lap_start,
            lapEnd: transition.stintB.lap_end,
            interceptS: degB.intercept_s,
            slopeSPerLap: degB.slope_s_per_lap,
            confidence: degB.confidence,
          },
          actualPitLap,
          candidateLap: effectiveCandidateLap,
          pitLossS,
        })
      : null;

  if (resultsStatus === "loading" || stintStatus === "loading") {
    return <div className="section-card"><h3>Loading…</h3></div>;
  }
  if (resultsStatus === "error") {
    return <div className="section-card"><h3>Couldn't load session data</h3><p>{resultsError.message}</p></div>;
  }
  if (!transitions.length) {
    return (
      <div className="section-card">
        <h3>Not enough stints to simulate</h3>
        <p>This driver needs at least two stints (one pit stop) for a "what if we'd pitted differently" comparison.</p>
      </div>
    );
  }

  const lowConfidence = LOW_CONFIDENCE.has(degA?.confidence) || LOW_CONFIDENCE.has(degB?.confidence);
  const sliderMin = transition.stintA.lap_start;
  const sliderMax = transition.stintB.lap_end !== null ? transition.stintB.lap_end - 1 : actualPitLap;

  return (
    <div className="stack">
      <div className="section-card">
        <div className="form-grid">
          <div className="control-row">
            <label>Driver</label>
            <select
              value={effectiveDriverId ?? ""}
              onChange={(e) => {
                setDriverId(e.target.value);
                setTransitionIndex(0);
                setCandidateLap(null);
              }}
            >
              {results.map((r) => (
                <option key={r.driver_id} value={r.driver_id}>
                  {r.drivers?.full_name ?? r.driver_id}
                </option>
              ))}
            </select>
          </div>
          <div className="control-row">
            <label>Pit stop</label>
            <select
              value={effectiveTransitionIndex}
              onChange={(e) => {
                setTransitionIndex(Number(e.target.value));
                setCandidateLap(null);
              }}
            >
              {transitions.map((t, i) => (
                <option key={i} value={i}>
                  Stint {t.stintA.stint_number} → {t.stintB.stint_number} (lap {t.stintA.lap_end})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="control-row slider-row">
          <label>Candidate pit lap: {effectiveCandidateLap}</label>
          <input
            type="range"
            min={sliderMin}
            max={sliderMax}
            value={effectiveCandidateLap ?? actualPitLap}
            onChange={(e) => setCandidateLap(Number(e.target.value))}
          />
        </div>

        <p className="strategy-note">
          Actual pit lap was {actualPitLap}. Real pit-lane loss for this driver, estimated from their own
          in-lap/out-lap vs. clean median pace: {pitLossS !== null ? `${pitLossS.toFixed(1)}s` : "N/A"}.
          Projections use each stint's own fitted degradation trend and assume it holds outside the laps
          actually run -- treat this as a directional estimate, not a lap-by-lap prediction.
        </p>
      </div>

      <div className="section-card">
        <h3>Simulated vs. actual</h3>
        {lowConfidence && (
          <p className="auth-error">
            One of these stints doesn't have enough clean laps for a trustworthy degradation trend --
            a simulated number here would be false precision, so none is shown.
          </p>
        )}
        {!lowConfidence && !simulation && (
          <p>Not enough data to simulate this pit stop yet.</p>
        )}
        {!lowConfidence && simulation && (
          <div className="detail-grid">
            <div className="info-block">
              <p>Actual (projected)</p>
              <strong>{simulation.actualProjectedTotalS.toFixed(1)}s</strong>
            </div>
            <div className="info-block">
              <p>Simulated</p>
              <strong>{simulation.simulatedTotalS.toFixed(1)}s</strong>
            </div>
            <div className={`info-block${simulation.deltaS < 0 ? " faster" : simulation.deltaS > 0 ? " slower" : ""}`}>
              <p>Delta</p>
              <strong>
                <AnimatedNumber value={simulation.deltaS} format={(v) => formatDelta(v, "s", 1)} />
              </strong>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default StrategyTab;
