"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const capacity = require("../capacity.js");

const widthM = 6;
const lengthM = 55;
const imagePoints = [
  { x: 500, y: 930 },
  { x: 790, y: 930 },
  { x: 700, y: 110 },
  { x: 600, y: 110 }
];

test("solveHomography maps the four world corners exactly", () => {
  const world = [
    { x: 0, y: 0 },
    { x: widthM, y: 0 },
    { x: widthM, y: lengthM },
    { x: 0, y: lengthM }
  ];
  const homography = capacity.solveHomography(world, imagePoints);
  for (let index = 0; index < 4; index += 1) {
    const projected = capacity.applyHomography(homography, world[index]);
    assert.ok(Math.abs(projected.x - imagePoints[index].x) < 1e-6);
    assert.ok(Math.abs(projected.y - imagePoints[index].y) < 1e-6);
  }
});

test("imageToWorld round-trips the near-right corner", () => {
  const calibration = capacity.calibrate({
    imagePoints,
    widthM,
    lengthM,
    imageSize: { width: 1280, height: 960 }
  });
  const world = capacity.applyHomography(
    calibration.imageToWorld,
    imagePoints[1]
  );
  assert.ok(Math.abs(world.x - widthM) < 1e-6);
  assert.ok(Math.abs(world.y) < 1e-6);
});

test("calibrate reports metric area, not pixel area disguised as metres", () => {
  const calibration = capacity.calibrate({
    imagePoints,
    widthM,
    lengthM,
    imageSize: { width: 1280, height: 960 }
  });
  assert.equal(calibration.areaM2, 330);
  assert.ok(calibration.pixelArea > 100000);
  assert.notEqual(calibration.areaM2, calibration.pixelArea);
  assert.ok(calibration.assumptions.knownWidth);
  assert.ok(calibration.assumptions.knownLength);
});

test("single known side requires an explicit aspect assumption", () => {
  const calibration = capacity.calibrateFromReference({
    imagePoints,
    knownSide: "width",
    knownM: 6,
    aspectRatio: 55 / 6,
    imageSize: { width: 1280, height: 960 }
  });
  assert.ok(Math.abs(calibration.areaM2 - 330) < 0.01);
  assert.equal(calibration.identifiability.status, "assumption-used");
  assert.ok(calibration.assumptions.note.includes("长宽比"));
});

test("invalid or self-intersecting corner order is rejected", () => {
  assert.throws(
    () =>
      capacity.calibrate({
        imagePoints: [
          { x: 500, y: 930 },
          { x: 790, y: 930 },
          { x: 600, y: 110 },
          { x: 700, y: 110 }
        ],
        widthM,
        lengthM
      }),
    /凸四边形/
  );
});

test("vanishing points are finite for a perspective trapezoid", () => {
  const result = capacity.vanishingPoints(imagePoints, {
    width: 1280,
    height: 960
  });
  assert.equal(result.longitudinal.atInfinity, false);
  assert.equal(result.transverse.atInfinity, true);
  assert.ok(Number.isFinite(result.longitudinal.point.x));
  assert.ok(Number.isFinite(result.longitudinal.point.y));
  assert.ok(result.warnings.length >= 1);
});

test("longitudinal capacity and area capacity use different assumptions", () => {
  const result = capacity.computeCapacities({
    widthM,
    lengthM,
    model: {
      trafficMode: "dead-end",
      longitudinalGapM: 2,
      areaFillFactor: 0.55
    }
  });
  const large = result.vehicles.large;
  assert.equal(large.reverseReserveM, 12);
  assert.equal(large.usableLengthM, 42);
  assert.equal(large.longitudinalSlots, 2);
  assert.equal(large.longitudinalCapacity, 2);
  assert.equal(large.areaCapacity, 3);
  assert.ok(large.areaCapacity > large.longitudinalCapacity);
  assert.match(large.formulas.longitudinal, /floor/);
});

test("through traffic removes the reverse reserve", () => {
  const through = capacity.computeCapacities({
    widthM,
    lengthM,
    model: { trafficMode: "through" }
  });
  const deadEnd = capacity.computeCapacities({
    widthM,
    lengthM,
    model: { trafficMode: "dead-end" }
  });
  assert.equal(through.vehicles.large.reverseReserveM, 0);
  assert.ok(
    through.vehicles.large.longitudinalCapacity >=
      deadEnd.vehicles.large.longitudinalCapacity
  );
});

test("load formula is exactly sum(count / capacity)", () => {
  const summary = capacity.loadSummary(
    { large: 1, medium: 2, small: 3 },
    { large: 2, medium: 4, small: 6 }
  );
  assert.ok(Math.abs(summary.totalRatio - 1.5) < 1e-12);
  assert.equal(summary.totalPercent, 150);
  assert.equal(summary.status, "over");
  assert.equal(summary.terms.length, 3);
});

test("zero capacity with nonzero count is invalid, not silently zero", () => {
  const summary = capacity.loadSummary(
    { large: 1, medium: 0, small: 0 },
    { large: 0, medium: 1, small: 1 }
  );
  assert.equal(summary.hasUnknown, true);
  assert.equal(summary.totalRatio, null);
  assert.equal(summary.status, "invalid");
});

test("Monte Carlo is deterministic and returns ordered intervals", () => {
  const first = capacity.monteCarloCapacity({
    widthM,
    lengthM,
    trials: 500,
    seed: 42
  });
  const second = capacity.monteCarloCapacity({
    widthM,
    lengthM,
    trials: 500,
    seed: 42
  });
  assert.deepEqual(first.summary, second.summary);
  for (const type of ["large", "medium", "small"]) {
    const interval = first.summary[type].longitudinal;
    assert.ok(interval.p05 <= interval.p50);
    assert.ok(interval.p50 <= interval.p95);
    assert.ok(interval.min <= interval.p05);
    assert.ok(interval.p95 <= interval.max);
  }
});

test("corner jitter does not fabricate an area uncertainty", () => {
  const calibration = capacity.calibrate({
    imagePoints,
    widthM,
    lengthM
  });
  const drift = capacity.cornerMappingDrift({
    calibration,
    sigmaPx: 3,
    trials: 100
  });
  assert.equal(drift.unit, "m");
  assert.ok(drift.drift.center.p95 >= 0);
  assert.match(drift.note, /容量只有在长宽由像素关系推断时才受影响/);
});

test("radial distortion sensitivity reports an area factor interval", () => {
  const result = capacity.distortionScaleSensitivity({
    k1Range: [-0.15, 0.05],
    maxNormalizedRadius: 1
  });
  assert.ok(result.areaFactorMin < 1);
  assert.ok(result.areaFactorMax > 1);
  assert.equal(result.factors.length, 2);
});

test("local metric scale converts pixels to metres only through the homography", () => {
  const calibration = capacity.calibrate({
    imagePoints,
    widthM,
    lengthM
  });
  const scale = capacity.localMetricScale(calibration, { x: 0, y: 0 });
  assert.ok(scale.metresPerPixel.isotropic > 0);
  assert.ok(scale.pixelsPerMetre.alongWorldWidth > 0);
  assert.ok(scale.pixelsPerMetre.alongWorldLength > 0);
});

test("vanishing-point sensitivity reports spread under corner jitter", () => {
  const calibration = capacity.calibrate({
    imagePoints,
    widthM,
    lengthM
  });
  const result = capacity.vanishingPointSensitivity({
    calibration,
    sigmaPx: 3,
    trials: 120
  });
  assert.ok(result.longitudinal.x.p05 <= result.longitudinal.x.p95);
  assert.ok(result.transverse.atInfinityRate >= 0);
  assert.ok(result.transverse.atInfinityRate <= 1);
  assert.match(result.note, /不是容量的直接误差项/);
});
