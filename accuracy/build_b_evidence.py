"""Compose a traceable B-run evidence sheet from frozen raw outputs.

No model call, no synthetic imagery and no box correction.  Each panel draws
exactly the bboxes stored in the selected run JSON.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "accuracy" / "runs" / "single_pass_v1"
CROPS = ROOT / "accuracy" / "crops" / "single_pass_v1" / "aisle"
PUBLIC = Path(
    r"D:\File\PROJECT\codex\codex-货车\all-sessions-can-see\coord\exploration\single-pass"
)
KEYS = ("north_600", "north_5", "south_2100")
RUNS = (("r1", "B_aisle"), ("r2", "B_aisle_r2"), ("r3", "B_aisle_r3"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def panel(key: str, run_tag: str, run_dir: str, panel_w: int = 430, panel_h: int = 790) -> Image.Image:
    raw_path = RUN_ROOT / run_dir / "doubao" / f"{key}.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    source = CROPS / f"{key}.jpg"
    with Image.open(source).convert("RGB") as image:
        scale = min(panel_w / image.width, (panel_h - 72) / image.height)
        resized = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    panel = Image.new("RGB", (panel_w, panel_h), (247, 247, 247))
    panel.paste(resized, ((panel_w - resized.width) // 2, 72))
    draw = ImageDraw.Draw(panel)
    title_font = font(22)
    label_font = font(16)
    draw.text(
        (8, 5),
        f"B {run_tag}  {key}  {payload['predicted_count']}/{payload['truth']}  calls={payload['call_count']}",
        fill=(20, 20, 20),
        font=title_font,
    )
    draw.text(
        (8, 36),
        f"err={payload['error']:+d}  原始 bbox，未修正",
        fill=(90, 90, 90),
        font=label_font,
    )
    for index, vehicle in enumerate(payload.get("vehicles") or [], 1):
        bbox = vehicle.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        x0 = (panel_w - resized.width) // 2 + bbox[0] * resized.width
        y0 = 72 + bbox[1] * resized.height
        x1 = (panel_w - resized.width) // 2 + bbox[2] * resized.width
        y1 = 72 + bbox[3] * resized.height
        draw.rectangle((x0, y0, x1, y1), outline=(255, 30, 30), width=3)
        draw.text((x0 + 3, max(73, y0 + 2)), str(index), fill=(255, 255, 0), font=label_font)
    return panel


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    panels = []
    manifest_runs = {}
    for key in KEYS:
        row = []
        manifest_runs[key] = {"truth": None, "runs": []}
        for run_tag, run_dir in RUNS:
            raw_path = RUN_ROOT / run_dir / "doubao" / f"{key}.json"
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
            manifest_runs[key]["truth"] = payload["truth"]
            manifest_runs[key]["runs"].append(
                {
                    "run": run_tag,
                    "raw_file": str(raw_path.relative_to(ROOT)),
                    "raw_sha256": sha256(raw_path),
                    "predicted_count": payload["predicted_count"],
                    "error": payload["error"],
                    "call_count": payload["call_count"],
                    "latency_total_s": payload["latency_total_s"],
                    "tokens_total": payload["tokens_total"],
                    "vehicles": payload.get("vehicles") or [],
                }
            )
            row.append(panel(key, run_tag, run_dir))
        panels.append(row)

    margin = 18
    panel_w, panel_h = panels[0][0].size
    header_h, footer_h = 86, 54
    width = margin * 4 + panel_w * 3
    height = header_h + margin + (panel_h + margin) * 3 + footer_h
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (margin, 12),
        "B 单次 aisle：真实原始输出对照（north_600 修复 / north_5 不稳定 / south_2100 稳定多计）",
        fill=(10, 10, 10),
        font=font(30),
    )
    draw.text(
        (margin, 52),
        "每格只画该 run 原始 JSON 的 bbox，未做任何框修正；count 正确不代表逐车框或身份正确。",
        fill=(120, 30, 30),
        font=font(19),
    )
    y = header_h + margin
    for row in panels:
        x = margin
        for item in row:
            sheet.paste(item, (x, y))
            x += panel_w + margin
        y += panel_h + margin
    draw.text(
        (margin, height - footer_h + 10),
        "source: accuracy/runs/single_pass_v1/B_aisle* / raw JSON; crops: accuracy/crops/single_pass_v1/aisle/; no new inference",
        fill=(80, 80, 80),
        font=font(15),
    )
    out = PUBLIC / "B_evidence.jpg"
    sheet.save(out, quality=92)
    manifest = {
        "schema": "single-pass-b-evidence-v1",
        "note": "All boxes are raw model outputs from the frozen B runs; no box correction, no new inference, no generated imagery.",
        "image": "B_evidence.jpg",
        "model": "doubao ep-20260828174616-dthpx",
        "prompt_sha256": "52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab",
        "keys": manifest_runs,
    }
    (PUBLIC / "B_evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({sheet.width}x{sheet.height}) and B_evidence_manifest.json")


if __name__ == "__main__":
    main()
