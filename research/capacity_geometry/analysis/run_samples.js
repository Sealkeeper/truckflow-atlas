"use strict";

const fs = require("node:fs");
const path = require("node:path");
const TC = require("../capacity.js");

const samples = {
  north: {
    frame: "assets/frames/north_5.jpg",
    imageSize: { width: 1280, height: 960 },
    imagePoints: [
      { x: 450, y: 935 },
      { x: 785, y: 935 },
      { x: 700, y: 110 },
      { x: 600, y: 110 }
    ],
    widthM: 6.0,
    lengthM: 55.0,
    assumption:
      "宽度约 6.0 m（两个 3 m 展位模数）；可见段长约 55 m（约 9 个 6 m 模数段）。"
  },
  south: {
    frame: "assets/frames/south_5.jpg",
    imageSize: { width: 1280, height: 960 },
    imagePoints: [
      { x: 470, y: 935 },
      { x: 770, y: 935 },
      { x: 700, y: 110 },
      { x: 588, y: 110 }
    ],
    widthM: 6.0,
    lengthM: 55.0,
    assumption:
      "采用与北侧相同的展位模数假设；远端被货车和顶部结构遮挡，长宽比假设的区间应更保守。"
  }
};

function loadRateInterval(summary, counts) {
  const low = TC.loadSummary(counts, {
    large: summary.large.longitudinal.p05,
    medium: summary.medium.longitudinal.p05,
    small: summary.small.longitudinal.p05
  });
  const median = TC.loadSummary(counts, {
    large: summary.large.longitudinal.p50,
    medium: summary.medium.longitudinal.p50,
    small: summary.small.longitudinal.p50
  });
  const high = TC.loadSummary(counts, {
    large: summary.large.longitudinal.p95,
    medium: summary.medium.longitudinal.p95,
    small: summary.small.longitudinal.p95
  });
  const values = [low, median, high]
    .map((item) => item.totalPercent)
    .filter((value) => value !== null);
  return {
    atP05CapacitiesPercent: low.totalPercent,
    atP50CapacitiesPercent: median.totalPercent,
    atP95CapacitiesPercent: high.totalPercent,
    minPercent: Math.min.apply(null, values),
    maxPercent: Math.max.apply(null, values)
  };
}

const results = {};

for (const [name, sample] of Object.entries(samples)) {
  const calibration = TC.calibrate({
    imagePoints: sample.imagePoints,
    widthM: sample.widthM,
    lengthM: sample.lengthM,
    imageSize: sample.imageSize
  });
  const model = {
    trafficMode: "dead-end",
    longitudinalGapM: 2.0,
    sideClearanceM: 0.4,
    endClearanceM: 0.5,
    lateralGapM: 0.8,
    laneCount: 1,
    areaFillFactor: 0.55
  };
  const capacities = TC.computeCapacities({
    widthM: sample.widthM,
    lengthM: sample.lengthM,
    model
  });
  const uncertainty = TC.monteCarloCapacity({
    widthM: sample.widthM,
    lengthM: sample.lengthM,
    model,
    trials: 20000,
    seed: 20251019
  });
  const vpSensitivity = TC.vanishingPointSensitivity({
    calibration,
    sigmaPx: 3,
    trials: 1000
  });
  const drift = TC.cornerMappingDrift({
    calibration,
    sigmaPx: 3,
    trials: 1000
  });
  const scaleAtCorners = calibration.worldPoints.map((point) =>
    TC.localMetricScale(calibration, point)
  );
  const distortion = TC.distortionScaleSensitivity({
    k1Range: [-0.15, 0.05],
    maxNormalizedRadius: 1
  });
  const counts = { large: 1, medium: 1, small: 1 };
  const loadRate = loadRateInterval(uncertainty.summary, counts);
  results[name] = {
    frame: sample.frame,
    assumption: sample.assumption,
    imagePoints: sample.imagePoints,
    widthM: sample.widthM,
    lengthM: sample.lengthM,
    areaM2: calibration.areaM2,
    pixelArea: calibration.pixelArea,
    reprojection: calibration.reprojection,
    vanishingPoints: calibration.vanishingPoints,
    vanishingPointSensitivity: vpSensitivity,
    cornerDrift: drift,
    localScaleAtCorners: scaleAtCorners,
    capacities: {
      large: capacities.vehicles.large.longitudinalCapacity,
      medium: capacities.vehicles.medium.longitudinalCapacity,
      small: capacities.vehicles.small.longitudinalCapacity,
      areaLarge: capacities.vehicles.large.areaCapacity,
      areaMedium: capacities.vehicles.medium.areaCapacity,
      areaSmall: capacities.vehicles.small.areaCapacity
    },
    formulas: {
      large: capacities.vehicles.large.formulas,
      medium: capacities.vehicles.medium.formulas,
      small: capacities.vehicles.small.formulas
    },
    uncertainty: uncertainty.summary,
    loadRate,
    distortion
  };
}

const output = {
  generatedAt: "2026-10-21",
  module: "research/capacity_geometry/capacity.js",
  conventions: {
    points:
      "单击顺序为近左、近右、远右、远左；世界坐标原点在近左角，x 为宽，y 为长。",
    warning:
      "容量是几何静态建议，不是经用户确认的额定容量，也不是吞吐量。"
  },
  model: {
    large: { lengthM: 16.5, widthM: 2.55, reverseReserveM: 12 },
    medium: { lengthM: 9.0, widthM: 2.5, reverseReserveM: 8 },
    small: { lengthM: 6.0, widthM: 2.2, reverseReserveM: 5 },
    longitudinalGapM: 2.0,
    sideClearanceM: 0.4,
    endClearanceM: 0.5,
    areaFillFactor: 0.55,
    trafficMode: "dead-end"
  },
  samples: results
};

const outputPath = path.join(__dirname, "sample-results.json");
fs.writeFileSync(outputPath, JSON.stringify(output, null, 2) + "\n");

console.log(JSON.stringify(output, null, 2));
