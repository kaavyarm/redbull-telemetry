import { describe, expect, it } from "vitest";
import { detectCorners, detectBrakingPoints } from "./trackGeometry";

// A square polyline (open, not wrapped -- the start/end points get zero
// curvature by construction, same as a real lap trace's first/last
// samples) with sharp vertices at indices 5, 10, 15. The wrap-around
// corner at the array boundary is not detectable from an open trace, so 3
// corners is the correct expectation here, not 4.
function squarePoints() {
  const points = [];
  for (let x = 0; x < 10; x += 2) points.push({ x, y: 0 }); // bottom edge
  for (let y = 0; y < 10; y += 2) points.push({ x: 10, y }); // right edge
  for (let x = 10; x > 0; x -= 2) points.push({ x, y: 10 }); // top edge
  for (let y = 10; y > 0; y -= 2) points.push({ x: 0, y }); // left edge
  return points;
}

describe("detectCorners", () => {
  it("finds the sharp vertices of a square path", () => {
    const corners = detectCorners(squarePoints());
    expect(corners.length).toBe(3);
    expect(corners.map((c) => c.number)).toEqual([1, 2, 3]);
  });

  it("finds nothing on a straight line", () => {
    const straight = Array.from({ length: 10 }, (_, i) => ({ x: i, y: 0 }));
    expect(detectCorners(straight)).toEqual([]);
  });

  it("returns empty for too few points", () => {
    expect(detectCorners([{ x: 0, y: 0 }, { x: 1, y: 1 }])).toEqual([]);
  });

  it("ignores null x/y samples", () => {
    const points = squarePoints().map((p, i) => (i === 3 ? { x: null, y: null } : p));
    expect(() => detectCorners(points)).not.toThrow();
  });
});

describe("detectBrakingPoints", () => {
  it("finds each brake 0->1 transition and maps it to the nearest position sample", () => {
    const telemetry = [
      { timeS: 0, brakeOn: 0 },
      { timeS: 1, brakeOn: 0 },
      { timeS: 2, brakeOn: 1 }, // rising edge
      { timeS: 3, brakeOn: 1 },
      { timeS: 4, brakeOn: 0 },
      { timeS: 5, brakeOn: 1 }, // second rising edge
    ];
    const position = [
      { timeS: 0, x: 0, y: 0 },
      { timeS: 2, x: 10, y: 10 },
      { timeS: 5, x: 20, y: 20 },
    ];
    const points = detectBrakingPoints(telemetry, position);
    expect(points).toEqual([
      { x: 10, y: 10 },
      { x: 20, y: 20 },
    ]);
  });

  it("returns empty when either series is empty", () => {
    expect(detectBrakingPoints([], [{ timeS: 0, x: 0, y: 0 }])).toEqual([]);
    expect(detectBrakingPoints([{ timeS: 0, brakeOn: 1 }], [])).toEqual([]);
  });
});
