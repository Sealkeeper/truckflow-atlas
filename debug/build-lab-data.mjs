import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const runsRoot = path.join(repoRoot, "accuracy", "runs");
const goldPath = path.join(repoRoot, "data", "gold", "camera_counts_v0.json");
const outputPath = path.join(repoRoot, "debug", "viewer", "lab-data.json");

const goldFile = JSON.parse(fs.readFileSync(goldPath, "utf8"));
const goldByKey = new Map(
  goldFile.samples.map((sample) => [`${sample.camera}_${sample.time}`, sample])
);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function pickRun(runFile) {
  if (!runFile || !fs.existsSync(runFile)) return null;
  const payload = readJson(runFile);
  const run = (payload.runs || []).find((item) => item.ok) || (payload.runs || [])[0] || null;
  if (!run) return null;
  const probe = path.basename(path.dirname(runFile)) !== "full_batch";
  const counts = run.parsed?.counts || {};
  const vehicles = Array.isArray(run.parsed?.vehicles) ? run.parsed.vehicles : [];
  return {
    ok: Boolean(run.ok),
    provider: run.model || "unknown",
    modelId: run.model_id || "",
    promptVersion: payload.prompt_version || "",
    latency: typeof run.latency_s === "number" ? run.latency_s : null,
    attempts: run.attempts ?? null,
    count: run.ok && typeof counts.total === "number" ? counts.total : null,
    types: {
      large: counts.large ?? null,
      medium: counts.medium ?? null,
      small: counts.small ?? null,
      unknown: counts.unknown ?? null
    },
    boxes: run.ok
      ? vehicles
          .filter((vehicle) => Array.isArray(vehicle.bbox) && vehicle.bbox.length === 4)
          .map((vehicle, index) => ({
            sequence: vehicle.sequence ?? index + 1,
            bbox: vehicle.bbox.map((value) => Number(value)),
            size: vehicle.size || "unknown",
            visible: vehicle.visible || "",
            uncertain: Boolean(vehicle.uncertain),
            evidence: vehicle.evidence || "",
            identity: vehicle.identity_clues || ""
          }))
      : [],
    vehicleCount: vehicles.length,
    uncertainCount: vehicles.filter((vehicle) => vehicle.uncertain).length,
    notes: run.ok ? run.parsed?.scene_notes || "" : "",
    error: run.ok ? "" : run.error || `HTTP ${run.status ?? "?"}`,
    probe
  };
}

function resultFor(key, filePath) {
  const gold = goldByKey.get(key);
  const [camera, timeText] = key.split("_");
  const pick = pickRun(filePath);
  if (!gold || !pick) {
    return {
      key,
      camera,
      time: Number(timeText),
      gold: gold?.total ?? null,
      ok: false,
      count: null,
      error: "缺少可用的实验文件"
    };
  }
  const delta = pick.ok && typeof pick.count === "number" ? pick.count - gold.total : null;
  return {
    key,
    camera,
    time: Number(timeText),
    gold: gold.total,
    goldReview: Boolean(gold.review),
    ...pick,
    delta
  };
}

const baseline = [];
for (const camera of ["north", "south"]) {
  for (let index = 0; index < 10; index += 1) {
    const time = [5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600][index];
    baseline.push(
      resultFor(`${camera}_${time}`, path.join(runsRoot, "full_batch", `${camera}_${time}.json`))
    );
  }
}

const probeRuns = [
  ["north_600", "promptv2_north_600.json"],
  ["north_300", "promptv2_north_300.json"],
  ["south_600", "promptv2_south_600.json"]
];
const doubaoV2 = probeRuns.map(([key, file]) => resultFor(key, path.join(runsRoot, file)));
const aiboxV2 = [resultFor("north_600", path.join(runsRoot, "promptv2_north_600_aibox.json"))];
const zhipuV2 = [resultFor("north_600", path.join(runsRoot, "promptv2_north_600_zhipu.json"))];

function summarize(rows) {
  const graded = rows.filter((row) => row.ok && typeof row.count === "number" && typeof row.gold === "number");
  const exact = graded.filter((row) => row.count === row.gold).length;
  const absError = graded.reduce((total, row) => total + Math.abs(row.count - row.gold), 0);
  const missing = graded.reduce((total, row) => total + Math.max(0, row.gold - row.count), 0);
  const extra = graded.reduce((total, row) => total + Math.max(0, row.count - row.gold), 0);
  const failed = rows.filter((row) => !row.ok).length;
  return {
    total: rows.length,
    graded: graded.length,
    exact,
    failed,
    mae: graded.length ? Number((absError / graded.length).toFixed(2)) : null,
    missing,
    extra,
    exactRate: graded.length ? Number(((exact / graded.length) * 100).toFixed(1)) : null
  };
}

const models = [
  {
    id: "doubao-full",
    label: "豆包 · 整帧基线 v1",
    short: "豆包 v1",
    detail: "20 帧全量基线，整帧输入，逐机位计数",
    provider: "doubao",
    results: baseline
  },
  {
    id: "doubao-v2",
    label: "豆包 · count_v2",
    short: "豆包 v2",
    detail: "由远到近扫描 + 逐车区分说明",
    provider: "doubao",
    results: doubaoV2
  },
  {
    id: "aibox-v2",
    label: "Aibox GLM-5.3-flash · count_v2",
    short: "Aibox v2",
    detail: "单样本验证：north_600 找回远端第 4 辆",
    provider: "aibox",
    results: aiboxV2
  },
  {
    id: "zhipu-v2",
    label: "智谱 GLM-4.5V · count_v2",
    short: "智谱 v2",
    detail: "单样本验证：north_600 对照",
    provider: "zhipu",
    results: zhipuV2
  }
].map((model) => ({
  ...model,
  metrics: summarize(model.results)
}));

const payload = {
  generatedAt: new Date().toISOString(),
  generatedAtLocal: new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai"
  }).format(new Date()),
  dataset: {
    name: "人工开发集 v0",
    scope: goldFile.scope,
    countDefinition: goldFile.count_definition,
    reviewNotes: goldFile.review_required || []
  },
  models
};

fs.writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(`已生成 ${outputPath}`);
for (const model of models) {
  console.log(
    `${model.short}: ${model.metrics.exact}/${model.metrics.graded} 完全正确, MAE ${model.metrics.mae}, 漏 ${model.metrics.missing}, 多 ${model.metrics.extra}`
  );
}
