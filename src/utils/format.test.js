import { describe, expect, it } from "vitest";
import { formatComparison, formatDelta, formatMetric, getConfidenceClass } from "./format";

describe("formatMetric", () => {
  it("formats a number with a unit", () => {
    expect(formatMetric(12.345, "s")).toBe("12.3 s");
  });

  it("formats a number without a unit", () => {
    expect(formatMetric(12.345)).toBe("12.3");
  });

  it("respects the digits argument", () => {
    expect(formatMetric(12.345, "s", 2)).toBe("12.35 s");
  });

  it.each([null, undefined, NaN, "not a number"])("returns N/A for %p", (value) => {
    expect(formatMetric(value)).toBe("N/A");
  });
});

describe("formatDelta", () => {
  it("prefixes positive deltas with +", () => {
    expect(formatDelta(1.2, "s")).toBe("+1.2 s");
  });

  it("does not double-prefix negative deltas", () => {
    expect(formatDelta(-1.2, "s")).toBe("-1.2 s");
  });

  it("returns N/A for non-numeric input", () => {
    expect(formatDelta(null)).toBe("N/A");
  });
});

describe("formatComparison", () => {
  it("returns N/A when either side is missing", () => {
    expect(formatComparison(null, 5)).toBe("N/A");
    expect(formatComparison(5, undefined)).toBe("N/A");
  });

  it("shows an arrow with delta for numeric values", () => {
    expect(formatComparison(10, 12, "psi")).toBe("10.0 psi → 12.0 psi (+2.0 psi)");
  });

  it("collapses identical string values to a single value", () => {
    expect(formatComparison("Map A", "Map A")).toBe("Map A");
  });

  it("shows an arrow (no delta) for differing string values", () => {
    expect(formatComparison("Map A", "Map B")).toBe("Map A → Map B");
  });
});

describe("getConfidenceClass", () => {
  it("lowercases a known confidence", () => {
    expect(getConfidenceClass("High")).toBe("high");
  });

  it("falls back to pending for missing input", () => {
    expect(getConfidenceClass(null)).toBe("pending");
    expect(getConfidenceClass(undefined)).toBe("pending");
  });
});
