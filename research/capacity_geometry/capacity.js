(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.TruckCapacity = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const EPS = 1e-9;

  /*
   * 建议值不是实测值。它们只是标定页的初始参数：
   * - 小/中/大型尺寸取常见厢式轻卡、两轴中卡、半挂重卡的保守占位；
   * - 纵向间距是前后车净距，不是中心距；
   * - 倒车余量只在尽端式通道使用，直通式通道应设为 0。
   */
  const VEHICLE_PRESETS = Object.freeze({
    small: Object.freeze({
      label: "小型货车",
      lengthM: 6.0,
      widthM: 2.2,
      reverseReserveM: 5.0,
      note: "厢式轻卡/轻型货车，按 6.0 x 2.2 m 占位"
    }),
    medium: Object.freeze({
      label: "中型货车",
      lengthM: 9.0,
      widthM: 2.5,
      reverseReserveM: 8.0,
      note: "两轴/三轴中卡，按 9.0 x 2.5 m 占位"
    }),
    large: Object.freeze({
      label: "大型货车",
      lengthM: 16.5,
      widthM: 2.55,
      reverseReserveM: 12.0,
      note: "半挂/长货厢重卡，按 16.5 x 2.55 m 占位"
    })
  });

  const DEFAULT_MODEL = Object.freeze({
    sideClearanceM: 0.4,
    endClearanceM: 0.5,
    longitudinalGapM: 2.0,
    lateralGapM: 0.8,
    laneCount: 1,
    areaFillFactor: 0.55,
    trafficMode: "dead-end"
  });

  class CalibrationError extends Error {
    constructor(code, message, details) {
      super(message);
      this.name = "CalibrationError";
      this.code = code;
      this.details = details || null;
    }
  }

  function finitePositive(value, name) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
      throw new CalibrationError(
        "INVALID_DIMENSION",
        `${name} 必须是大于 0 的有限数值`,
        { name, value }
      );
    }
    return number;
  }

  function asPoint(point) {
    if (Array.isArray(point)) {
      return { x: Number(point[0]), y: Number(point[1]) };
    }
    return { x: Number(point.x), y: Number(point.y) };
  }

  function validateImagePoints(points) {
    if (!Array.isArray(points) || points.length !== 4) {
      throw new CalibrationError(
        "INVALID_POINTS",
        "需要 4 个按“近左、近右、远右、远左”顺序点击的通道角点"
      );
    }
    const result = points.map(asPoint);
    for (const point of result) {
      if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) {
        throw new CalibrationError(
          "INVALID_POINTS",
          "角点坐标必须为有限像素值"
        );
      }
    }
    if (!isConvexQuad(result)) {
      throw new CalibrationError(
        "NON_CONVEX_QUAD",
        "四个角点没有形成凸四边形，请按通道路面边界重新点击"
      );
    }
    return result;
  }

  function cross2(a, b, c) {
    return (
      (b.x - a.x) * (c.y - a.y) -
      (b.y - a.y) * (c.x - a.x)
    );
  }

  function polygonArea(points) {
    let twice = 0;
    for (let i = 0; i < points.length; i += 1) {
      const a = asPoint(points[i]);
      const b = asPoint(points[(i + 1) % points.length]);
      twice += a.x * b.y - b.x * a.y;
    }
    return Math.abs(twice) / 2;
  }

  function isConvexQuad(points) {
    if (points.length !== 4) return false;
    let sign = 0;
    for (let i = 0; i < 4; i += 1) {
      const value = cross2(
        points[i],
        points[(i + 1) % 4],
        points[(i + 2) % 4]
      );
      if (Math.abs(value) < EPS) return false;
      const current = Math.sign(value);
      if (sign === 0) sign = current;
      if (current !== sign) return false;
    }
    return polygonArea(points) > EPS;
  }

  function normalizePoints(points) {
    const n = points.length;
    let cx = 0;
    let cy = 0;
    for (const point of points) {
      cx += point.x;
      cy += point.y;
    }
    cx /= n;
    cy /= n;
    let meanDistance = 0;
    for (const point of points) {
      meanDistance += Math.hypot(point.x - cx, point.y - cy);
    }
    meanDistance /= n;
    if (meanDistance < EPS) {
      throw new CalibrationError(
        "DEGENERATE_POINTS",
        "标定点全部重合，无法求解单应矩阵"
      );
    }
    const scale = Math.SQRT2 / meanDistance;
    const normalized = points.map((point) => ({
      x: (point.x - cx) * scale,
      y: (point.y - cy) * scale
    }));
    const transform = [
      [scale, 0, -scale * cx],
      [0, scale, -scale * cy],
      [0, 0, 1]
    ];
    return { points: normalized, transform };
  }

  function multiply3x3(a, b) {
    return [
      [
        a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
        a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
        a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2]
      ],
      [
        a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
        a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
        a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2]
      ],
      [
        a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
        a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
        a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2]
      ]
    ];
  }

  function invert3x3(matrix) {
    const a = matrix[0][0];
    const b = matrix[0][1];
    const c = matrix[0][2];
    const d = matrix[1][0];
    const e = matrix[1][1];
    const f = matrix[1][2];
    const g = matrix[2][0];
    const h = matrix[2][1];
    const i = matrix[2][2];
    const A = e * i - f * h;
    const B = -(d * i - f * g);
    const C = d * h - e * g;
    const det = a * A + b * B + c * C;
    if (Math.abs(det) < EPS) {
      throw new CalibrationError(
        "SINGULAR_HOMOGRAPHY",
        "单应矩阵奇异，角点近似共线，无法反投影"
      );
    }
    const invDet = 1 / det;
    return [
      [A * invDet, -(b * i - c * h) * invDet, (b * f - c * e) * invDet],
      [B * invDet, (a * i - c * g) * invDet, -(a * f - c * d) * invDet],
      [C * invDet, -(a * h - b * g) * invDet, (a * e - b * d) * invDet]
    ];
  }

  function solveLinearSystem(matrix, vector) {
    const n = vector.length;
    const augmented = matrix.map((row, index) => row.concat([vector[index]]));
    for (let column = 0; column < n; column += 1) {
      let pivot = column;
      for (let row = column + 1; row < n; row += 1) {
        if (Math.abs(augmented[row][column]) > Math.abs(augmented[pivot][column])) {
          pivot = row;
        }
      }
      if (Math.abs(augmented[pivot][column]) < EPS) {
        throw new CalibrationError(
          "SINGULAR_DLT",
          "单应矩阵求解失败：标定点退化"
        );
      }
      if (pivot !== column) {
        const swap = augmented[column];
        augmented[column] = augmented[pivot];
        augmented[pivot] = swap;
      }
      const divisor = augmented[column][column];
      for (let k = column; k <= n; k += 1) {
        augmented[column][k] /= divisor;
      }
      for (let row = 0; row < n; row += 1) {
        if (row === column) continue;
        const factor = augmented[row][column];
        if (Math.abs(factor) < EPS) continue;
        for (let k = column; k <= n; k += 1) {
          augmented[row][k] -= factor * augmented[column][k];
        }
      }
    }
    return augmented.map((row) => row[n]);
  }

  /**
   * 求解 world -> image 的单应矩阵。world 点顺序同样为
   * 近左、近右、远右、远左；单位是米。
   */
  function solveHomography(sourcePoints, destinationPoints) {
    if (sourcePoints.length !== 4 || destinationPoints.length !== 4) {
      throw new CalibrationError(
        "INVALID_POINTS",
        "单应矩阵需要各 4 个对应点"
      );
    }
    const source = sourcePoints.map(asPoint);
    const destination = destinationPoints.map(asPoint);
    const normalizedSource = normalizePoints(source);
    const normalizedDestination = normalizePoints(destination);
    const matrix = [];
    const vector = [];
    for (let index = 0; index < 4; index += 1) {
      const s = normalizedSource.points[index];
      const d = normalizedDestination.points[index];
      matrix.push([s.x, s.y, 1, 0, 0, 0, -d.x * s.x, -d.x * s.y]);
      vector.push(d.x);
      matrix.push([0, 0, 0, s.x, s.y, 1, -d.y * s.x, -d.y * s.y]);
      vector.push(d.y);
    }
    const solution = solveLinearSystem(matrix, vector);
    const normalizedH = [
      [solution[0], solution[1], solution[2]],
      [solution[3], solution[4], solution[5]],
      [solution[6], solution[7], 1]
    ];
    const destinationTransformInverse = invert3x3(
      normalizedDestination.transform
    );
    const homography = multiply3x3(
      multiply3x3(destinationTransformInverse, normalizedH),
      normalizedSource.transform
    );
    const scale = homography[2][2] || 1;
    return homography.map((row) => row.map((value) => value / scale));
  }

  function applyHomography(matrix, point) {
    const p = asPoint(point);
    const denominator =
      matrix[2][0] * p.x + matrix[2][1] * p.y + matrix[2][2];
    if (Math.abs(denominator) < EPS) {
      throw new CalibrationError(
        "POINT_AT_INFINITY",
        "该点落在单应变换的无穷远线上"
      );
    }
    return {
      x:
        (matrix[0][0] * p.x + matrix[0][1] * p.y + matrix[0][2]) /
        denominator,
      y:
        (matrix[1][0] * p.x + matrix[1][1] * p.y + matrix[1][2]) /
        denominator
    };
  }

  function lineThrough(a, b) {
    return [
      a.y - b.y,
      b.x - a.x,
      a.x * b.y - b.x * a.y
    ];
  }

  function intersectLines(lineA, lineB) {
    const point = [
      lineA[1] * lineB[2] - lineA[2] * lineB[1],
      lineA[2] * lineB[0] - lineA[0] * lineB[2],
      lineA[0] * lineB[1] - lineA[1] * lineB[0]
    ];
    const normalizer = Math.hypot(lineA[0], lineA[1]) * Math.hypot(lineB[0], lineB[1]);
    const z = point[2];
    if (Math.abs(z) < EPS * Math.max(1, normalizer)) {
      return {
        atInfinity: true,
        point: null,
        direction: { x: point[0], y: point[1] }
      };
    }
    return {
      atInfinity: false,
      point: { x: point[0] / z, y: point[1] / z }
    };
  }

  function vanishingPoints(points, imageSize) {
    const [nearLeft, nearRight, farRight, farLeft] = points;
    const left = intersectLines(
      lineThrough(nearLeft, farLeft),
      lineThrough(nearRight, farRight)
    );
    const near = intersectLines(
      lineThrough(nearLeft, nearRight),
      lineThrough(farLeft, farRight)
    );
    const width = imageSize && Number(imageSize.width);
    const height = imageSize && Number(imageSize.height);
    const inside = (intersection) => {
      if (!intersection.point || !width || !height) return null;
      return (
        intersection.point.x >= 0 &&
        intersection.point.x <= width &&
        intersection.point.y >= 0 &&
        intersection.point.y <= height
      );
    };
    const warnings = [];
    if (left.atInfinity) {
      warnings.push("纵向边近似平行：画面可能接近正视，纵向消失点不可靠。");
    } else if (inside(left)) {
      warnings.push("纵向消失点落在画面内：角点顺序或通道边界可能有误。");
    }
    if (near.atInfinity) {
      warnings.push("两条端边近似平行：透视很弱，端边方向不能用于校验。");
    } else if (inside(near)) {
      warnings.push("横向消失点落在画面内：请检查角点是否形成箭头形四边形。");
    }
    return {
      longitudinal: left,
      transverse: near,
      warnings
    };
  }

  function reprojectionErrors(matrix, sourcePoints, destinationPoints) {
    const errors = [];
    for (let index = 0; index < sourcePoints.length; index += 1) {
      const projected = applyHomography(matrix, sourcePoints[index]);
      const target = asPoint(destinationPoints[index]);
      errors.push(
        Math.hypot(projected.x - target.x, projected.y - target.y)
      );
    }
    return {
      perPoint: errors,
      rms: Math.sqrt(
        errors.reduce((sum, value) => sum + value * value, 0) /
          errors.length
      ),
      max: Math.max.apply(null, errors)
    };
  }

  /**
   * 四角标定。widthM / lengthM 必须同时已知或明确假设；
   * 只给一个尺寸时请使用 calibrateFromReference()，它会要求长宽比。
   */
  function calibrate(options) {
    const opts = options || {};
    const imagePoints = validateImagePoints(opts.imagePoints);
    const widthM = finitePositive(opts.widthM, "通道宽度 widthM");
    const lengthM = finitePositive(opts.lengthM, "通道长度 lengthM");
    const worldPoints = [
      { x: 0, y: 0 },
      { x: widthM, y: 0 },
      { x: widthM, y: lengthM },
      { x: 0, y: lengthM }
    ];
    const worldToImage = solveHomography(worldPoints, imagePoints);
    const worldPointsForCheck = worldPoints.map((point) => point);
    const residual = reprojectionErrors(
      worldToImage,
      worldPointsForCheck,
      imagePoints
    );
    if (residual.max > 0.5) {
      throw new CalibrationError(
        "HOMOGRAPHY_RESIDUAL",
        "单应矩阵回投残差异常，请检查角点",
        residual
      );
    }
    return {
      imagePoints,
      worldPoints,
      widthM,
      lengthM,
      areaM2: widthM * lengthM,
      pixelArea: polygonArea(imagePoints),
      worldToImage,
      imageToWorld: invert3x3(worldToImage),
      reprojection: residual,
      vanishingPoints: vanishingPoints(imagePoints, opts.imageSize),
      assumptions: {
        knownWidth: opts.knownWidth !== false,
        knownLength: opts.knownLength !== false,
        note:
          opts.note ||
          "面积由输入的米制长宽确定；单应矩阵只负责把路面映射到该矩形。"
      }
    };
  }

  /**
   * 只给一个实长时的标定入口。
   * knownSide = "width" 或 "length"；另一维通过长宽比假设得到。
   * 该模式会明确标记 assumedAspectRatio，不能在报告中当作实测面积。
   */
  function calibrateFromReference(options) {
    const opts = options || {};
    const knownSide = opts.knownSide === "length" ? "length" : "width";
    const knownM = finitePositive(opts.knownM, "已知实长 knownM");
    const aspectRatio = finitePositive(
      opts.aspectRatio === undefined ? 8.0 : opts.aspectRatio,
      "长宽比 aspectRatio"
    );
    const widthM = knownSide === "width" ? knownM : knownM / aspectRatio;
    const lengthM = knownSide === "width" ? knownM * aspectRatio : knownM;
    const calibration = calibrate({
      imagePoints: opts.imagePoints,
      widthM,
      lengthM,
      imageSize: opts.imageSize,
      knownWidth: knownSide === "width",
      knownLength: knownSide === "length",
      note:
        "仅一个米制尺寸已知；另一维来自长宽比假设 " +
        aspectRatio.toFixed(2) +
        ":1，属于估计而非测量。"
    });
    calibration.assumedAspectRatio = aspectRatio;
    calibration.knownSide = knownSide;
    calibration.knownM = knownM;
    calibration.identifiability = {
      status: "assumption-used",
      explanation:
        "四个角点只能确定透视映射；已知一个长度不足以同时确定矩形的长和宽。" +
        "本结果把长宽比作为显式假设，并在敏感性分析中传播。"
    };
    return calibration;
  }

  function resolveVehicle(type, overrides) {
    const preset = VEHICLE_PRESETS[type];
    if (!preset) {
      throw new CalibrationError("UNKNOWN_VEHICLE", `未知车型: ${type}`);
    }
    const value = (overrides && overrides[type]) || {};
    return {
      type,
      label: value.label || preset.label,
      lengthM: finitePositive(
        value.lengthM === undefined ? preset.lengthM : value.lengthM,
        `${preset.label}长度`
      ),
      widthM: finitePositive(
        value.widthM === undefined ? preset.widthM : value.widthM,
        `${preset.label}宽度`
      ),
      reverseReserveM: Math.max(
        0,
        Number(
          value.reverseReserveM === undefined
            ? preset.reverseReserveM
            : value.reverseReserveM
        )
      ),
      note: value.note || preset.note
    };
  }

  function floorWithTolerance(value) {
    return Math.max(0, Math.floor(value + 1e-9));
  }

  /**
   * 每个车型按“整条通道都放该车型”计算容量。
   * 纵向排布：N = floor((L_eff + gap) / (L_vehicle + gap))
   * 面积利用：N = floor(W_eff * L_eff * fill / (W_vehicle * L_vehicle))
   */
  function computeCapacities(options) {
    const opts = options || {};
    const widthM = finitePositive(opts.widthM, "通道宽度 widthM");
    const lengthM = finitePositive(opts.lengthM, "通道长度 lengthM");
    const model = Object.assign({}, DEFAULT_MODEL, opts.model || {});
    const sideClearanceM = Math.max(0, Number(model.sideClearanceM));
    const endClearanceM = Math.max(0, Number(model.endClearanceM));
    const longitudinalGapM = Math.max(0, Number(model.longitudinalGapM));
    const lateralGapM = Math.max(0, Number(model.lateralGapM));
    const laneCount = Math.max(1, Math.floor(Number(model.laneCount) || 1));
    const areaFillFactor = Math.min(
      1,
      Math.max(0.01, Number(model.areaFillFactor))
    );
    const trafficMode = model.trafficMode === "through" ? "through" : "dead-end";
    const usableWidthM = Math.max(0, widthM - 2 * sideClearanceM);
    const usableAreaM2 = Math.max(
      0,
      usableWidthM * Math.max(0, lengthM - 2 * endClearanceM)
    );
    const vehicles = opts.vehicles || {};
    const types = opts.types || ["large", "medium", "small"];
    const results = {};
    for (const type of types) {
      const vehicle = resolveVehicle(type, vehicles);
      const reverseReserveM =
        trafficMode === "dead-end" ? vehicle.reverseReserveM : 0;
      const usableLengthM = Math.max(
        0,
        lengthM - 2 * endClearanceM - reverseReserveM
      );
      const longitudinalSlots = floorWithTolerance(
        (usableLengthM + longitudinalGapM) /
          (vehicle.lengthM + longitudinalGapM)
      );
      const lateralSlots = floorWithTolerance(
        (usableWidthM + lateralGapM) /
          (vehicle.widthM + lateralGapM)
      );
      const longitudinalCapacity = longitudinalSlots * laneCount;
      const areaCapacity = floorWithTolerance(
        (usableAreaM2 * areaFillFactor) /
          (vehicle.lengthM * vehicle.widthM)
      );
      const packedGridCapacity = longitudinalSlots * lateralSlots;
      results[type] = {
        type,
        label: vehicle.label,
        vehicle,
        trafficMode,
        reverseReserveM,
        usableWidthM,
        usableLengthM,
        usableAreaM2,
        longitudinalSlots,
        lateralSlots,
        laneCount,
        longitudinalCapacity,
        areaCapacity,
        packedGridCapacity,
        difference: areaCapacity - longitudinalCapacity,
        formulas: {
          longitudinal:
            `floor((${usableLengthM.toFixed(2)} + ${longitudinalGapM}) / ` +
            `(${vehicle.lengthM.toFixed(2)} + ${longitudinalGapM})) × ${laneCount}`,
          area:
            `floor(${usableAreaM2.toFixed(1)} × ${areaFillFactor.toFixed(2)} / ` +
            `(${vehicle.lengthM.toFixed(2)} × ${vehicle.widthM.toFixed(2)}))`
        }
      };
    }
    return {
      widthM,
      lengthM,
      usableWidthM,
      usableAreaM2,
      model: {
        sideClearanceM,
        endClearanceM,
        longitudinalGapM,
        lateralGapM,
        laneCount,
        areaFillFactor,
        trafficMode
      },
      types,
      vehicles: results,
      note:
        "两种容量均为几何静态估计，不是吞吐量，也不是经用户确认的额定容量。"
    };
  }

  /**
   * 产品口径固定为 Σ(N_i / C_i)。counts / capacities 以车型为键。
   */
  function loadSummary(counts, capacities) {
    const types = ["large", "medium", "small"];
    const terms = [];
    let total = 0;
    let hasUnknown = false;
    for (const type of types) {
      const rawCount = counts && counts[type] !== undefined ? counts[type] : 0;
      const rawCapacity =
        capacities && capacities[type] !== undefined ? capacities[type] : 0;
      const count = Number(rawCount);
      const capacity = Number(rawCapacity);
      if (!Number.isFinite(count) || count < 0 || !Number.isFinite(capacity) || capacity < 0) {
        throw new CalibrationError(
          "INVALID_LOAD_INPUT",
          "车辆数量与容量必须是非负有限数"
        );
      }
      let ratio;
      if (capacity > 0) {
        ratio = count / capacity;
      } else if (count === 0) {
        ratio = 0;
      } else {
        ratio = null;
        hasUnknown = true;
      }
      if (ratio !== null) total += ratio;
      terms.push({ type, count, capacity, ratio });
    }
    return {
      terms,
      totalRatio: hasUnknown ? null : total,
      totalPercent: hasUnknown ? null : total * 100,
      hasUnknown,
      formula: "Σ(当前该型数量 / 该型容量)",
      status: hasUnknown
        ? "invalid"
        : total < 0.7
          ? "low"
          : total <= 1.0
            ? "high"
            : "over"
    };
  }

  function mulberry32(seed) {
    let state = seed >>> 0;
    return function random() {
      state += 0x6d2b79f5;
      let t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function normalRandom(random) {
    let u = 0;
    let v = 0;
    while (u === 0) u = random();
    while (v === 0) v = random();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  function quantile(sortedValues, probability) {
    if (!sortedValues.length) return null;
    const position = (sortedValues.length - 1) * probability;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sortedValues[lower];
    const fraction = position - lower;
    return (
      sortedValues[lower] * (1 - fraction) +
      sortedValues[upper] * fraction
    );
  }

  function summarizeValues(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    return {
      min: sorted[0],
      p05: quantile(sorted, 0.05),
      p50: quantile(sorted, 0.5),
      p95: quantile(sorted, 0.95),
      max: sorted[sorted.length - 1],
      mean:
        sorted.reduce((sum, value) => sum + value, 0) /
        Math.max(1, sorted.length)
    };
  }

  /**
   * 传播长度、宽度、车型尺寸、净距和倒车余量的输入不确定性。
   * 角点像素误差不会改变“双维已知”情形的面积，但会改变地面映射；
   * 本函数单独返回边角映射漂移，避免把不存在的面积误差说成存在。
   */
  function monteCarloCapacity(options) {
    const opts = options || {};
    const widthM = finitePositive(opts.widthM, "通道宽度 widthM");
    const lengthM = finitePositive(opts.lengthM, "通道长度 lengthM");
    const trials = Math.min(50000, Math.max(100, Number(opts.trials) || 4000));
    const seed = Number.isFinite(opts.seed) ? opts.seed : 20251019;
    const random = mulberry32(seed);
    const widthRelativeSigma =
      opts.widthRelativeSigma === undefined ? 0.08 : opts.widthRelativeSigma;
    const lengthRelativeSigma =
      opts.lengthRelativeSigma === undefined ? 0.12 : opts.lengthRelativeSigma;
    const vehicleRelativeSigma =
      opts.vehicleRelativeSigma === undefined ? 0.05 : opts.vehicleRelativeSigma;
    const gapAbsoluteSigma =
      opts.gapAbsoluteSigma === undefined ? 0.5 : opts.gapAbsoluteSigma;
    const reverseRelativeSigma =
      opts.reverseRelativeSigma === undefined ? 0.15 : opts.reverseRelativeSigma;
    const model = Object.assign({}, DEFAULT_MODEL, opts.model || {});
    const baseTypes = opts.types || ["large", "medium", "small"];
    const samples = {};
    for (const type of baseTypes) {
      samples[type] = { longitudinal: [], area: [] };
    }
    const baseVehicles = opts.vehicles || {};
    for (let trial = 0; trial < trials; trial += 1) {
      const sampledWidth = Math.max(
        2.0,
        widthM * (1 + normalRandom(random) * widthRelativeSigma)
      );
      const sampledLength = Math.max(
        5.0,
        lengthM * (1 + normalRandom(random) * lengthRelativeSigma)
      );
      const sampledVehicles = {};
      for (const type of baseTypes) {
        const base = resolveVehicle(type, baseVehicles);
        const factor = Math.max(
          0.7,
          1 + normalRandom(random) * vehicleRelativeSigma
        );
        sampledVehicles[type] = {
          lengthM: base.lengthM * factor,
          widthM: base.widthM * (1 + normalRandom(random) * vehicleRelativeSigma * 0.4),
          reverseReserveM: Math.max(
            0,
            base.reverseReserveM *
              (1 + normalRandom(random) * reverseRelativeSigma)
          )
        };
      }
      const sampledModel = Object.assign({}, model, {
        longitudinalGapM: Math.max(
          0,
          Number(model.longitudinalGapM) +
            normalRandom(random) * gapAbsoluteSigma
        ),
        areaFillFactor: Math.min(
          0.95,
          Math.max(
            0.15,
            Number(model.areaFillFactor) + normalRandom(random) * 0.05
          )
        )
      });
      const capacities = computeCapacities({
        widthM: sampledWidth,
        lengthM: sampledLength,
        model: sampledModel,
        vehicles: sampledVehicles,
        types: baseTypes
      });
      for (const type of baseTypes) {
        samples[type].longitudinal.push(
          capacities.vehicles[type].longitudinalCapacity
        );
        samples[type].area.push(capacities.vehicles[type].areaCapacity);
      }
    }
    const summary = {};
    for (const type of baseTypes) {
      summary[type] = {
        longitudinal: summarizeValues(samples[type].longitudinal),
        area: summarizeValues(samples[type].area)
      };
    }
    return {
      trials,
      seed,
      widthM,
      lengthM,
      assumptions: {
        widthRelativeSigma,
        lengthRelativeSigma,
        vehicleRelativeSigma,
        gapAbsoluteSigma,
        reverseRelativeSigma
      },
      summary,
      cornerNote:
        "若长宽直接输入，角点像素误差只影响地面位置映射，不改变面积估计；" +
        "若用长宽比推断另一维，则长宽比误差已由 lengthRelativeSigma 传入。"
    };
  }

  /**
   * 由四角像素抖动估计地面映射漂移。返回归一化坐标中的
   * 中心点/四角漂移，用于提示“点选误差”而不伪造容量误差。
   */
  function cornerMappingDrift(options) {
    const opts = options || {};
    const calibration = opts.calibration;
    if (!calibration || !calibration.worldToImage) {
      throw new CalibrationError(
        "MISSING_CALIBRATION",
        "cornerMappingDrift 需要 calibrate() 的结果"
      );
    }
    const sigma = Math.max(0, Number(opts.sigmaPx) || 3);
    const trials = Math.min(10000, Math.max(50, Number(opts.trials) || 500));
    const random = mulberry32(
      Number.isFinite(opts.seed) ? opts.seed : 7788
    );
    const reference = [
      { x: 0, y: 0 },
      { x: calibration.widthM, y: 0 },
      { x: calibration.widthM, y: calibration.lengthM },
      { x: 0, y: calibration.lengthM },
      { x: calibration.widthM / 2, y: calibration.lengthM / 2 }
    ];
    const nominal = reference.map((point) =>
      applyHomography(calibration.worldToImage, point)
    );
    const drift = reference.map(() => []);
    for (let trial = 0; trial < trials; trial += 1) {
      const jittered = calibration.imagePoints.map((point) => ({
        x: point.x + normalRandom(random) * sigma,
        y: point.y + normalRandom(random) * sigma
      }));
      if (!isConvexQuad(jittered)) continue;
      let imageToWorld;
      try {
        imageToWorld = invert3x3(
          solveHomography(
            [
              { x: 0, y: 0 },
              { x: calibration.widthM, y: 0 },
              { x: calibration.widthM, y: calibration.lengthM },
              { x: 0, y: calibration.lengthM }
            ],
            jittered
          )
        );
      } catch (error) {
        continue;
      }
      for (let index = 0; index < nominal.length; index += 1) {
        const mapped = applyHomography(imageToWorld, nominal[index]);
        drift[index].push(
          Math.hypot(
            mapped.x - reference[index].x,
            mapped.y - reference[index].y
          )
        );
      }
    }
    const labels = ["nearLeft", "nearRight", "farRight", "farLeft", "center"];
    const result = {};
    for (let index = 0; index < labels.length; index += 1) {
      result[labels[index]] = summarizeValues(drift[index]);
    }
    return {
      sigmaPx: sigma,
      trials,
      unit: "m",
      drift: result,
      note:
        "该漂移表示点击误差造成的米制位置误差；容量只有在长宽由像素关系推断时才受影响。"
    };
  }

  /**
   * 单应矩阵在某世界点的局部尺度。用于把“点击偏移多少像素”
   * 翻译成“边界在地面上偏移多少米”，而不是直接把像素比例当米。
   */
  function localMetricScale(calibration, worldPoint, epsilon) {
    if (!calibration || !calibration.worldToImage) {
      throw new CalibrationError(
        "MISSING_CALIBRATION",
        "localMetricScale 需要 calibrate() 的结果"
      );
    }
    const point = asPoint(worldPoint);
    const h = Math.max(1e-4, Number(epsilon) || 0.02);
    const atXPlus = applyHomography(calibration.worldToImage, {
      x: point.x + h,
      y: point.y
    });
    const atXMinus = applyHomography(calibration.worldToImage, {
      x: point.x - h,
      y: point.y
    });
    const atYPlus = applyHomography(calibration.worldToImage, {
      x: point.x,
      y: point.y + h
    });
    const atYMinus = applyHomography(calibration.worldToImage, {
      x: point.x,
      y: point.y - h
    });
    const j11 = (atXPlus.x - atXMinus.x) / (2 * h);
    const j21 = (atXPlus.y - atXMinus.y) / (2 * h);
    const j12 = (atYPlus.x - atYMinus.x) / (2 * h);
    const j22 = (atYPlus.y - atYMinus.y) / (2 * h);
    const det = j11 * j22 - j12 * j21;
    if (Math.abs(det) < EPS) {
      throw new CalibrationError(
        "DEGENERATE_JACOBIAN",
        "局部映射退化，无法计算米/像素尺度"
      );
    }
    const inv = [
      [j22 / det, -j12 / det],
      [-j21 / det, j11 / det]
    ];
    return {
      worldPoint: point,
      pixelsPerMetre: {
        alongWorldWidth: Math.hypot(j11, j21),
        alongWorldLength: Math.hypot(j12, j22)
      },
      metresPerPixel: {
        imageX: Math.hypot(inv[0][0], inv[1][0]),
        imageY: Math.hypot(inv[0][1], inv[1][1]),
        isotropic: Math.sqrt(Math.abs(1 / det))
      },
      determinant: det
    };
  }

  /**
   * 角点像素抖动造成的消失点分布。只用于诊断边界/矩形假设是否稳定。
   */
  function vanishingPointSensitivity(options) {
    const opts = options || {};
    const calibration = opts.calibration;
    if (!calibration || !calibration.imagePoints) {
      throw new CalibrationError(
        "MISSING_CALIBRATION",
        "vanishingPointSensitivity 需要 calibrate() 的结果"
      );
    }
    const sigma = Math.max(0, Number(opts.sigmaPx) || 3);
    const trials = Math.min(10000, Math.max(50, Number(opts.trials) || 500));
    const random = mulberry32(
      Number.isFinite(opts.seed) ? opts.seed : 9981
    );
    const longitudinal = { x: [], y: [] };
    const transverse = { x: [], y: [] };
    let longitudinalAtInfinity = 0;
    let transverseAtInfinity = 0;
    for (let trial = 0; trial < trials; trial += 1) {
      const jittered = calibration.imagePoints.map((point) => ({
        x: point.x + normalRandom(random) * sigma,
        y: point.y + normalRandom(random) * sigma
      }));
      if (!isConvexQuad(jittered)) continue;
      const points = vanishingPoints(jittered);
      if (points.longitudinal.atInfinity) {
        longitudinalAtInfinity += 1;
      } else {
        longitudinal.x.push(points.longitudinal.point.x);
        longitudinal.y.push(points.longitudinal.point.y);
      }
      if (points.transverse.atInfinity) {
        transverseAtInfinity += 1;
      } else {
        transverse.x.push(points.transverse.point.x);
        transverse.y.push(points.transverse.point.y);
      }
    }
    const summarize = (axis, atInfinity) => ({
      atInfinityRate: atInfinity / Math.max(1, trials),
      x: axis.x.length ? summarizeValues(axis.x) : null,
      y: axis.y.length ? summarizeValues(axis.y) : null
    });
    return {
      sigmaPx: sigma,
      trials,
      longitudinal: summarize(longitudinal, longitudinalAtInfinity),
      transverse: summarize(transverse, transverseAtInfinity),
      note:
        "消失点散布说明四角定义的透视方向是否稳定；" +
        "若容量采用直接输入的米制长宽，它不是容量的直接误差项。"
    };
  }

  function distortionScaleSensitivity(options) {
    const opts = options || {};
    const k1Range = Array.isArray(opts.k1Range) ? opts.k1Range : [-0.15, 0.05];
    const radius = Math.max(0, Number(opts.maxNormalizedRadius) || 1);
    const r2 = radius * radius;
    const factors = k1Range.map((k1) => {
      const radial = 1 + Number(k1) * r2;
      return {
        k1: Number(k1),
        scale: radial,
        areaScale: radial * radial
      };
    });
    return {
      k1Range: k1Range.slice(),
      maxNormalizedRadius: radius,
      factors,
      areaFactorMin: Math.min.apply(null, factors.map((item) => item.areaScale)),
      areaFactorMax: Math.max.apply(null, factors.map((item) => item.areaScale)),
      note:
        "一阶径向畸变近似：未校正半径 r 处的尺度约乘 (1+k1 r²)，" +
        "面积近似乘其平方。k1 必须来自镜头标定；未知时应增大长宽误差区间。"
    };
  }

  return {
    VEHICLE_PRESETS,
    DEFAULT_MODEL,
    CalibrationError,
    solveHomography,
    invert3x3,
    applyHomography,
    polygonArea,
    isConvexQuad,
    vanishingPoints,
    reprojectionErrors,
    calibrate,
    calibrateFromReference,
    computeCapacities,
    loadSummary,
    monteCarloCapacity,
    cornerMappingDrift,
    localMetricScale,
    vanishingPointSensitivity,
    distortionScaleSensitivity,
    summarizeValues,
    mulberry32
  };
});
