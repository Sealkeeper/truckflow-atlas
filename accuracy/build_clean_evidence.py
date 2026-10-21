"""Build the four-error contact sheet for the clean aisle baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ERROR_IDS = ("north_300", "north_5", "north_600", "south_2100")
PANEL_W = 520
PANEL_H = 940
HEADER_H = 72
TITLE_H = 52
FOOTER_H = 58


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_boxes(
    panel: Image.Image,
    run_path: Path,
    label_font: ImageFont.FreeTypeFont,
) -> None:
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    successful = [run for run in payload.get("runs", []) if run.get("ok")]
    if not successful:
        return
    vehicles = (successful[-1].get("parsed") or {}).get("vehicles", [])
    draw = ImageDraw.Draw(panel)
    width, height = panel.size
    for index, vehicle in enumerate(vehicles, start=1):
        bbox = vehicle.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (
            round(float(bbox[0]) * width),
            round(float(bbox[1]) * height),
            round(float(bbox[2]) * width),
            round(float(bbox[3]) * height),
        )
        colour = (255, 48, 48)
        draw.rectangle((x0, y0, x1, y1), outline=colour, width=5)
        text = f"P{index}"
        text_box = draw.textbbox((0, 0), text, font=label_font)
        tw = text_box[2] - text_box[0] + 12
        th = text_box[3] - text_box[1] + 8
        tx = max(2, min(x0, width - tw - 2))
        ty = max(2, y0 - th)
        draw.rectangle((tx, ty, tx + tw, ty + th), fill=colour)
        draw.text((tx + 6, ty + 2), text, fill=(255, 255, 255), font=label_font)


def build(runs: Path, review_json: Path, out: Path) -> None:
    report = json.loads(review_json.read_text(encoding="utf-8"))
    rows = {row["sample_id"]: row for row in report["rows"]}
    title_font = font(25)
    metric_font = font(22)
    label_font = font(17)
    footer_font = font(18)

    sheet = Image.new(
        "RGB",
        (PANEL_W * 2, TITLE_H + (PANEL_H + HEADER_H) * 2 + FOOTER_H),
        (24, 27, 32),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (18, 12),
        "Clean aisle baseline | four error frames",
        fill=(245, 246, 248),
        font=title_font,
    )
    for index, sample_id in enumerate(ERROR_IDS):
        row = rows[sample_id]
        column = index % 2
        line = index // 2
        left = column * PANEL_W
        top = TITLE_H + HEADER_H + line * (PANEL_H + HEADER_H)
        header_top = top - HEADER_H
        draw.text(
            (left + 12, header_top + 8),
            f"{sample_id} | truth={row['gold']} pred={row['predicted']} "
            f"error={row['error']:+d}",
            fill=(255, 218, 120),
            font=metric_font,
        )
        draw.text(
            (left + 12, header_top + 42),
            "red boxes = model candidates for this single aisle view",
            fill=(180, 186, 196),
            font=label_font,
        )
        image_path = ROOT / "accuracy" / "crops" / f"{sample_id}_aisle.jpg"
        with Image.open(image_path) as image:
            panel = image.convert("RGB").resize(
                (PANEL_W, PANEL_H), Image.Resampling.LANCZOS
            )
        draw_boxes(panel, runs / f"{sample_id}_aisle.json", label_font)
        sheet.paste(panel, (left, top))
        draw.line(
            ((left, top - 1), (left + PANEL_W - 1, top - 1)),
            fill=(80, 86, 96),
            width=1,
        )
        draw.line(
            ((left, top), (left, top + PANEL_H - 1)),
            fill=(80, 86, 96),
            width=1,
        )

    draw.text(
        (18, sheet.height - FOOTER_H + 14),
        "truth: user-final-review-v2-2026-10-21.json | runs: aisle_clean (one aisle view per sample)",
        fill=(180, 186, 196),
        font=footer_font,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92, subsampling=0)
    print(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "accuracy" / "runs" / "aisle_clean")
    parser.add_argument(
        "--review",
        type=Path,
        default=ROOT / "accuracy" / "reviewed" / "evaluation-clean-v1.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "accuracy" / "evidence" / "clean_baseline" / "errors_contact.jpg",
    )
    args = parser.parse_args()
    build(args.runs, args.review, args.out)


if __name__ == "__main__":
    main()
