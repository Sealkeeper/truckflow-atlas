"""Ask models about explicitly labelled cross-camera candidate pairs."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from extract_frames import font
from model_client import ROOT, load_env, probe


PAIRS = [
    {"case": "t600_red_positive", "north": ("north_600", "N6"), "south": ("south_600", "S6"), "gold": "yes"},
    {"case": "t600_white_positive", "north": ("north_600", "N8"), "south": ("south_600", "S7"), "gold": "yes"},
    {"case": "t600_blue_vs_far_red", "north": ("north_600", "N4"), "south": ("south_600", "S3"), "gold": "no"},
    {"case": "t600_blue_vs_red_cab", "north": ("north_600", "N5"), "south": ("south_600", "S5"), "gold": "no"},
    {"case": "t1200_red_positive", "north": ("north_1200", "N7"), "south": ("south_1200", "S6"), "gold": "yes"},
    {"case": "t1200_white_positive", "north": ("north_1200", "N8"), "south": ("south_1200", "S7"), "gold": "yes"},
    {"case": "t1200_blue_vs_far_red", "north": ("north_1200", "N4"), "south": ("south_1200", "S2"), "gold": "no"},
    {"case": "t1200_red_vs_red_cab", "north": ("north_1200", "N7"), "south": ("south_1200", "S5"), "gold": "no"},
]

PROMPT = """左格是北机位候选，右格是南机位同一时刻候选；两机位存在重叠，但视角不同。
问题只有一项：它们是否同一物理车辆？

判定规则：
1. 至少两个语义特征一致才可判 yes，例如货厢颜色和结构、车头颜色和形状、文字/标识、车顶特征。
2. 同色不是充分证据；红车与另一辆红车可能不同。
3. 车头与货厢属于同一车时不要拆开；但两格裁片可能只显示局部。
4. 视角、尺度变化导致无法确认时必须 answer=uncertain，不能猜。

只输出严格 JSON：
{"answer":"yes|no|uncertain","shared_features":["至少两个"],"conflicting_features":[""],"reason":"","review":true}"""


def build_sheet(pair: dict[str, Any]) -> Path:
    frames_dir = ROOT / "assets" / "frames"
    panel_w, panel_h, label_h = 620, 460, 58
    sheet = Image.new("RGB", (panel_w * 2, panel_h + label_h), "#071018")
    draw = ImageDraw.Draw(sheet)
    for index, side in enumerate(("north", "south")):
        observation, candidate = pair[side]
        frame = frames_dir / f"{observation.split('_')[0]}_t{observation.split('_')[1]}.jpg"
        candidates = json.loads((ROOT / "data" / "candidates.json").read_text(encoding="utf-8"))
        bbox = next(item["bbox"] for item in candidates[observation] if item["candidate"] == candidate)
        with Image.open(frame).convert("RGB") as image:
            width, height = image.size
            x0, y0, x1, y1 = bbox
            pad_x, pad_y = (x1 - x0) * 0.10, (y1 - y0) * 0.05
            pixels = (
                max(0, round((x0 - pad_x) * width)),
                max(0, round((y0 - pad_y) * height)),
                min(width, round((x1 + pad_x) * width)),
                min(height, round((y1 + pad_y) * height)),
            )
            crop = ImageOps.contain(image.crop(pixels), (panel_w - 24, panel_h - 16), Image.Resampling.LANCZOS)
        sheet.paste(crop, (index * panel_w + (panel_w - crop.width) // 2, label_h + (panel_h - crop.height) // 2))
        draw.text(
            (index * panel_w + 18, 14),
            f"{side.upper()} {observation} / {candidate}",
            fill="#63f5d7",
            font=font(25, True),
        )
    output = ROOT / "assets" / "sheets" / f"pair_{pair['case']}.jpg"
    sheet.save(output, quality=94, subsampling=0)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="doubao,aibox")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_env()
    out_dir = ROOT / "data" / "runs" / "pair_probes"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for pair in PAIRS:
        image = build_sheet(pair)
        for model in args.models.split(","):
            target = out_dir / f"{pair['case']}__{model.strip()}.json"
            previous_ok = False
            if target.exists():
                previous_ok = bool(
                    json.loads(target.read_text(encoding="utf-8")).get("run", {}).get("ok")
                )
            if args.force or not previous_ok:
                tasks.append((pair, image, model.strip(), target))
    print(f"scheduled {len(tasks)} pair probes")

    def run(task: tuple[dict[str, Any], Path, str, Path]) -> tuple[Path, dict[str, Any]]:
        pair, image, model, target = task
        result = probe(model, [image], PROMPT, max_tokens=1400)
        payload = {
            "case": pair["case"],
            "north_candidate": pair["north"],
            "south_candidate": pair["south"],
            "gold_answer": pair["gold"],
            "image": str(image.relative_to(ROOT)),
            "prompt": PROMPT,
            "run": result,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target, result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, task) for task in tasks]
        for future in as_completed(futures):
            target, result = future.result()
            if result.get("ok"):
                parsed = result.get("parsed", {})
                print(
                    f"{target.name}: answer={parsed.get('answer')} review={parsed.get('review')} "
                    f"latency={result['latency_s']}s"
                )
            else:
                print(f"{target.name}: FAILED {result.get('error')}")


if __name__ == "__main__":
    main()
