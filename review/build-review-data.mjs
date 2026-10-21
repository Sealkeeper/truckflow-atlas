import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const gold = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "data", "gold", "camera_counts_v0.json"), "utf8")
);
const blockers = JSON.parse(
  fs.readFileSync(path.join(here, "definition-blockers.json"), "utf8")
);

const offsets = [-2, -1, 0, 1, 2];
const samples = gold.samples.map((sample) => {
  const key = `${sample.camera}_${sample.time}`;
  const frames = offsets.map((offset) => {
    const suffix = offset === 0 ? "0" : offset > 0 ? `+${offset}` : `${offset}`;
    const relative = `frames/${key}_${suffix}.jpg`;
    return {
      offset,
      path: relative,
      exists: fs.existsSync(path.join(here, relative))
    };
  });
  const clip = `clips/${key}.mp4`;
  const crop = `crops/${key}.jpg`;
  return {
    key,
    camera: sample.camera,
    time: sample.time,
    provisionalTotal: sample.total,
    provisionalTypes: {
      large: sample.large,
      medium: sample.medium,
      small: sample.small
    },
    reviewFlag: Boolean(sample.review),
    original: `assets/frames/${key}.jpg`,
    crop,
    cropExists: fs.existsSync(path.join(here, crop)),
    frames,
    clip: fs.existsSync(path.join(here, clip)) ? clip : null,
    clipStart: Math.max(0, sample.time - 15)
  };
});

const payload = {
  generatedAt: new Date().toISOString(),
  status: "ai-single-annotator-provisional-pending-final-human-review",
  warning:
    "初标来自 AI 对外部视频抽帧的目视计数，不是人工金标准，也没有逐车框。连续帧和视频只用于帮助终审，不改变这一事实。",
  countDefinition:
    "每张画面内独立可辨的货车车体；叉车、轿车、面包车、行人排除；牵引车与其挂车计一辆；明确独立且可辨的货厢单独计。",
  definitionBlockers: blockers,
  samples
};

fs.writeFileSync(
  path.join(here, "review-data.json"),
  `${JSON.stringify(payload, null, 2)}\n`,
  "utf8"
);
console.log(`已生成 ${samples.length} 个复核样本`);
