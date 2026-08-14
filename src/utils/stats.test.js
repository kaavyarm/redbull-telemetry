import { describe, expect, it } from "vitest";
import { mean, standardDeviation } from "./stats";

describe("mean", () => {
  it("averages a list of numbers", () => {
    expect(mean([1, 2, 3, 4])).toBe(2.5);
  });

  it("returns null for an empty list", () => {
    expect(mean([])).toBeNull();
  });

  it("returns the value itself for a single-element list", () => {
    expect(mean([7])).toBe(7);
  });
});

describe("standardDeviation", () => {
  it("returns null for fewer than 2 values", () => {
    expect(standardDeviation([])).toBeNull();
    expect(standardDeviation([5])).toBeNull();
  });

  it("returns 0 for identical values", () => {
    expect(standardDeviation([4, 4, 4])).toBe(0);
  });

  it("computes population standard deviation", () => {
    // population variance of [2, 4, 4, 4, 5, 5, 7, 9] is 4, so stdDev is 2
    expect(standardDeviation([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(2, 5);
  });
});
