/*
 * Static demo payload. Per-camera counts are copied from the human-reviewed
 * development sample set `camera-counts-v0`; they are not acceptance results.
 * No reliable vehicle boxes exist in that source, so every sample keeps
 * `boxes: []` and the UI must not invent vehicle positions.
 */
window.TRUCKFLOW_DEMO = {
  schemaVersion: "ui-static-demo-v1",
  dataset: {
    id: "camera-counts-v0",
    label: "广交会撤换展 · A区天花双机位",
    status: "DEMO / 未验收",
    source: "2025-10-19 21:59–22:43 人工开发集样帧",
    sourcePath: "data/gold/camera_counts_v0.json",
    durationSeconds: 2659,
    startTime: "2025-10-19T21:59:26+08:00",
    displayWindow: "44:19",
    sampleIntervalSeconds: 300,
    countDefinition: "每张画面中的独立货车车体；叉车、轿车、面包车、行人排除；牵引车与挂车计一辆。",
    mergeDefinition: "跨机位唯一车辆数需要外观、位置与时间连续性证据，当前未合并。",
    boxStatus: "unavailable",
    boxMessage: "框待后端返回"
  },
  cameras: [
    {
      id: "north",
      code: "CAM-N",
      name: "天花北",
      imagePath: "assets/frames/north_{time}.jpg",
      offsetSeconds: 0,
      calibrationStatus: "未校准"
    },
    {
      id: "south",
      code: "CAM-S",
      name: "天花南",
      imagePath: "assets/frames/south_{time}.jpg",
      offsetSeconds: 0,
      calibrationStatus: "未校准"
    }
  ],
  capacityDefaults: {
    large: 8,
    medium: 6,
    small: 4,
    status: "pending_user_confirmation",
    label: "待用户确认"
  },
  crops: {
    north: {
      large: "assets/frames/crops/north-wide.jpg",
      medium: "assets/frames/crops/north-large.jpg",
      small: "assets/frames/crops/north-wide.jpg",
      unknown: "assets/frames/crops/north-large.jpg"
    },
    south: {
      large: "assets/frames/crops/south-large.jpg",
      medium: "assets/frames/crops/south-medium.jpg",
      small: "assets/frames/crops/south-review.jpg",
      unknown: "assets/frames/crops/south-review.jpg"
    }
  },
  samples: [
    {
      time: 5,
      north: { total: 3, large: 3, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 3, large: 2, medium: 1, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南机位远处棕色货体可能与中段车辆相连，需确认独立挂车身份。",
      reviewReasons: ["挂车归属", "车型边界"]
    },
    {
      time: 300,
      north: { total: 3, large: 3, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 4, large: 3, medium: 1, small: 0, unknown: 0, review: false, boxes: [] },
      note: "两侧画面计数稳定，跨机位身份仍未合并。",
      reviewReasons: []
    },
    {
      time: 600,
      north: { total: 4, large: 4, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 5, large: 3, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南机位底部边缘红色货厢可能属于相邻通道，通道边界待用户确认。",
      reviewReasons: ["通道边界", "遮挡"]
    },
    {
      time: 900,
      north: { total: 3, large: 3, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 5, large: 3, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南机位底部边缘车辆归属仍需复核；不得用北机位数量补齐。",
      reviewReasons: ["通道边界"]
    },
    {
      time: 1200,
      north: { total: 3, large: 3, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 5, large: 3, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南北合计出现峰值，但重叠车辆未去重，不能视为通道唯一车辆峰值。",
      reviewReasons: ["跨机位去重"]
    },
    {
      time: 1500,
      north: { total: 2, large: 2, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 5, large: 3, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "北机位数量下降，南机位仍保持 5 辆次；跨画面变化可能来自视角差异。",
      reviewReasons: ["跨机位去重", "通道边界"]
    },
    {
      time: 1800,
      north: { total: 2, large: 2, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 4, large: 2, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南机位有两辆中型车，车型一致票数不足，逐车证据保持待复核。",
      reviewReasons: ["车型争议", "通道边界"]
    },
    {
      time: 2100,
      north: { total: 2, large: 2, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 4, large: 2, medium: 2, small: 0, unknown: 0, review: true, boxes: [] },
      note: "画面内合计下降不自动等同于车辆离场，可能只是进入另一机位盲区。",
      reviewReasons: ["盲区", "跨机位去重"]
    },
    {
      time: 2400,
      north: { total: 3, large: 3, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 3, large: 2, medium: 1, small: 0, unknown: 0, review: true, boxes: [] },
      note: "南机位底部红色货厢再次出现，通道有效区域需要确认。",
      reviewReasons: ["通道边界"]
    },
    {
      time: 2600,
      north: { total: 2, large: 2, medium: 0, small: 0, unknown: 0, review: false, boxes: [] },
      south: { total: 3, large: 2, medium: 1, small: 0, unknown: 0, review: true, boxes: [] },
      note: "画面对应业务时间约 22:42:46，接近 44:19 展示窗口尾端。",
      reviewReasons: ["通道边界"]
    }
  ]
};
