import { describe, expect, it } from "vitest";
import {
  buildLapComparisonSeries,
  buildLapPositionSeries,
  buildLapTelemetrySeries,
  computeLapDelta,
  downsampleRows,
  nearestAt,
  parsePgInterval,
  toChartNumber,
} from "./telemetry";

describe("toChartNumber", () => {
  it("parses numeric strings", () => {
    expect(toChartNumber("12.5")).toBe(12.5);
  });

  it.each([null, undefined, ""])("falls back for %p", (value) => {
    expect(toChartNumber(value, -1)).toBe(-1);
  });

  it("falls back for non-numeric strings", () => {
    expect(toChartNumber("not a number", 0)).toBe(0);
  });
});

describe("downsampleRows", () => {
  it("returns rows unchanged when under the cap", () => {
    const rows = Array.from({ length: 10 }, (_, i) => i);
    expect(downsampleRows(rows, 400)).toEqual(rows);
  });

  it("reduces row count to at most maxPoints when over the cap", () => {
    const rows = Array.from({ length: 1000 }, (_, i) => i);
    const result = downsampleRows(rows, 400);
    expect(result.length).toBeLessThanOrEqual(400);
    expect(result.length).toBeGreaterThan(0);
  });

  it("always keeps the first row", () => {
    const rows = Array.from({ length: 1000 }, (_, i) => i);
    expect(downsampleRows(rows, 400)[0]).toBe(0);
  });
});

describe("parsePgInterval", () => {
  it("parses plain HH:MM:SS", () => {
    expect(parsePgInterval("00:01:23")).toBe(83);
  });

  it("parses fractional seconds", () => {
    expect(parsePgInterval("00:01:23.456")).toBeCloseTo(83.456, 6);
  });

  it("parses a days prefix", () => {
    expect(parsePgInterval("1 day 00:00:01")).toBe(86401);
  });

  it("parses a negative interval (e.g. lap_time_evolution's delta_to_prev_lap when a lap is faster)", () => {
    expect(parsePgInterval("-00:00:05.108")).toBeCloseTo(-5.108, 6);
  });

  it("returns null for null/undefined/garbage", () => {
    expect(parsePgInterval(null)).toBeNull();
    expect(parsePgInterval(undefined)).toBeNull();
    expect(parsePgInterval("not an interval")).toBeNull();
  });
});

describe("buildLapTelemetrySeries", () => {
  it("zeroes the time axis to the first sample and maps every channel", () => {
    const rows = [
      { session_time: "00:01:00", speed: "200", throttle: "80", brake: false, n_gear: 5, rpm: "10500", drs: 0 },
      { session_time: "00:01:00.5", speed: "210", throttle: "90", brake: false, n_gear: 6, rpm: "11000", drs: 1 },
    ];
    const series = buildLapTelemetrySeries(rows);
    expect(series).toEqual([
      { timeS: 0, speedKph: 200, throttlePct: 80, brakeOn: 0, nGear: 5, rpm: 10500, drs: 0 },
      { timeS: 0.5, speedKph: 210, throttlePct: 90, brakeOn: 0, nGear: 6, rpm: 11000, drs: 1 },
    ]);
  });

  it("sorts out-of-order rows by session_time first", () => {
    const rows = [
      { session_time: "00:01:00.5", speed: "210", throttle: "90", brake: false, n_gear: 6, rpm: "11000", drs: 1 },
      { session_time: "00:01:00", speed: "200", throttle: "80", brake: false, n_gear: 5, rpm: "10500", drs: 0 },
    ];
    const series = buildLapTelemetrySeries(rows);
    expect(series.map((r) => r.timeS)).toEqual([0, 0.5]);
  });

  it("returns an empty array for no rows", () => {
    expect(buildLapTelemetrySeries([])).toEqual([]);
  });

  it("maps brake=true to brakeOn=1", () => {
    const rows = [{ session_time: "00:00:00", speed: "1", throttle: "0", brake: true, n_gear: 1, rpm: "1", drs: 0 }];
    expect(buildLapTelemetrySeries(rows)[0].brakeOn).toBe(1);
  });
});

describe("buildLapComparisonSeries", () => {
  function makeRows(count, speedFn) {
    return Array.from({ length: count }, (_, i) => ({
      session_time: `00:00:${String(i).padStart(2, "0")}`,
      speed: String(speedFn(i)),
      throttle: "80",
      brake: false,
      n_gear: 5,
      rpm: "10000",
      drs: 0,
    }));
  }

  it("returns empty for empty input on either side", () => {
    expect(buildLapComparisonSeries([], makeRows(5, () => 200))).toEqual([]);
    expect(buildLapComparisonSeries(makeRows(5, () => 200), [])).toEqual([]);
  });

  it("produces the requested number of points, capped by the shorter lap's duration", () => {
    const a = makeRows(20, () => 200);
    const b = makeRows(10, () => 190);
    const series = buildLapComparisonSeries(a, b, 50);
    expect(series).toHaveLength(50);
    expect(series[series.length - 1].timeS).toBeLessThanOrEqual(9);
  });

  it("carries both laps' speed at each aligned point", () => {
    const a = makeRows(5, () => 200);
    const b = makeRows(5, () => 180);
    const series = buildLapComparisonSeries(a, b, 5);
    for (const point of series) {
      expect(point.aSpeedKph).toBe(200);
      expect(point.bSpeedKph).toBe(180);
    }
  });
});

describe("buildLapComparisonSeries", () => {
  function makeRows(count, fn) {
    return Array.from({ length: count }, (_, i) => ({
      session_time: `00:00:${String(i).padStart(2, "0")}`,
      speed: String(fn(i)),
      throttle: "80",
      brake: i % 2 === 0,
      n_gear: 5,
      rpm: "10000",
      drs: 0,
    }));
  }

  it("carries all six channels for both laps, not just speed", () => {
    const a = makeRows(5, () => 200);
    const b = makeRows(5, () => 180);
    const series = buildLapComparisonSeries(a, b, 5);
    for (const point of series) {
      expect(point).toHaveProperty("aBrakeOn");
      expect(point).toHaveProperty("bBrakeOn");
      expect(point).toHaveProperty("aNGear");
      expect(point).toHaveProperty("bNGear");
      expect(point).toHaveProperty("aRpm");
      expect(point).toHaveProperty("bRpm");
      expect(point).toHaveProperty("aDrs");
      expect(point).toHaveProperty("bDrs");
    }
  });
});

describe("nearestAt", () => {
  it("finds the closest row by timeS", () => {
    const series = [{ timeS: 0 }, { timeS: 1 }, { timeS: 2.5 }];
    expect(nearestAt(series, 2.2)).toEqual({ timeS: 2.5 });
  });

  it("returns the only row for a single-row series", () => {
    expect(nearestAt([{ timeS: 5 }], 100)).toEqual({ timeS: 5 });
  });
});

describe("buildLapPositionSeries", () => {
  it("zeroes the time axis and maps x/y/status", () => {
    const rows = [
      { session_time: "00:01:00", x: "10", y: "20", status: "OnTrack" },
      { session_time: "00:01:00.5", x: "12", y: "22", status: "OnTrack" },
    ];
    expect(buildLapPositionSeries(rows)).toEqual([
      { timeS: 0, x: 10, y: 20, status: "OnTrack" },
      { timeS: 0.5, x: 12, y: 22, status: "OnTrack" },
    ]);
  });

  it("returns an empty array for no rows", () => {
    expect(buildLapPositionSeries([])).toEqual([]);
  });
});

describe("computeLapDelta", () => {
  it("returns null if either lap is missing", () => {
    expect(computeLapDelta(null, { lap_time: "00:01:00" })).toBeNull();
  });

  it("computes B-minus-A for lap time and each sector", () => {
    const lapA = { lap_time: "00:01:30", sector1_time: "00:00:30", sector2_time: "00:00:30", sector3_time: "00:00:30" };
    const lapB = { lap_time: "00:01:28", sector1_time: "00:00:29", sector2_time: "00:00:30", sector3_time: "00:00:29" };

    expect(computeLapDelta(lapA, lapB)).toEqual({
      lapTimeDeltaS: -2,
      sector1DeltaS: -1,
      sector2DeltaS: 0,
      sector3DeltaS: -1,
    });
  });

  it("leaves a sector null if either side is missing it", () => {
    const lapA = { lap_time: "00:01:30", sector1_time: null, sector2_time: "00:00:30", sector3_time: "00:00:30" };
    const lapB = { lap_time: "00:01:28", sector1_time: "00:00:29", sector2_time: "00:00:30", sector3_time: "00:00:29" };
    expect(computeLapDelta(lapA, lapB).sector1DeltaS).toBeNull();
  });
});
