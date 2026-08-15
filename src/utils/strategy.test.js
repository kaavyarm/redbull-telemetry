import { describe, expect, it } from "vitest";
import { computeCleanMedianPace, computeRealPitLoss, simulateAlternatePitLap } from "./strategy";

function lap(lapNumber, seconds, opts = {}) {
  const pad = (n, len) => String(n).padStart(len, "0");
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return {
    lap_number: lapNumber,
    lap_time: `00:${pad(mins, 2)}:${pad(secs, 6)}`,
    deleted: false,
    pit_in_time: null,
    pit_out_time: null,
    ...opts,
  };
}

describe("computeCleanMedianPace", () => {
  it("returns the median of clean lap times", () => {
    const laps = [lap(1, 90.0), lap(2, 91.0), lap(3, 89.0)];
    expect(computeCleanMedianPace(laps)).toBeCloseTo(90.0, 5);
  });

  it("excludes deleted and pit laps", () => {
    const laps = [
      lap(1, 90.0),
      lap(2, 200.0, { pit_in_time: "00:01:20" }),
      lap(3, 91.0),
      lap(4, 50.0, { deleted: true }),
    ];
    expect(computeCleanMedianPace(laps)).toBeCloseTo(90.5, 5);
  });

  it("returns null for no clean laps", () => {
    expect(computeCleanMedianPace([lap(1, 90.0, { deleted: true })])).toBeNull();
  });
});

describe("computeRealPitLoss", () => {
  it("sums the in-lap and out-lap loss vs. clean median", () => {
    const laps = [
      lap(5, 95.0, { pit_in_time: "00:01:30" }),
      lap(6, 110.0, { pit_out_time: "00:00:05" }),
    ];
    expect(computeRealPitLoss(laps, 5, 90.0)).toBeCloseTo(5.0 + 20.0, 5);
  });

  it("returns null when the clean median itself is null", () => {
    expect(computeRealPitLoss([], 5, null)).toBeNull();
  });

  it("clamps a nonsensical negative loss to zero", () => {
    const laps = [lap(5, 80.0, { pit_in_time: "00:01:20" })];
    expect(computeRealPitLoss(laps, 5, 90.0)).toBe(0);
  });
});

describe("simulateAlternatePitLap", () => {
  const stintA = { lapStart: 1, interceptS: 90, slopeSPerLap: 0.5, confidence: "high" };
  const stintB = { lapStart: 6, lapEnd: 10, interceptS: 88, slopeSPerLap: 0.3, confidence: "high" };

  it("returns ~zero delta when the candidate lap matches the actual pit lap", () => {
    const out = simulateAlternatePitLap({ stintA, stintB, actualPitLap: 5, candidateLap: 5, pitLossS: 22 });
    expect(out).not.toBeNull();
    expect(out.deltaS).toBeCloseTo(0, 5);
  });

  it("shows a real delta for a different candidate lap", () => {
    const out = simulateAlternatePitLap({ stintA, stintB, actualPitLap: 5, candidateLap: 6, pitLossS: 22 });
    expect(out.deltaS).toBeCloseTo(3.5, 5);
  });

  it("returns null when either stint's degradation confidence is too low", () => {
    const lowConfidenceA = { ...stintA, confidence: "low" };
    const out = simulateAlternatePitLap({ stintA: lowConfidenceA, stintB, actualPitLap: 5, candidateLap: 6, pitLossS: 22 });
    expect(out).toBeNull();
  });

  it("returns null when the candidate lap is out of range", () => {
    const out = simulateAlternatePitLap({ stintA, stintB, actualPitLap: 5, candidateLap: 20, pitLossS: 22 });
    expect(out).toBeNull();
  });

  it("returns null when pit loss couldn't be computed", () => {
    const out = simulateAlternatePitLap({ stintA, stintB, actualPitLap: 5, candidateLap: 6, pitLossS: null });
    expect(out).toBeNull();
  });
});
