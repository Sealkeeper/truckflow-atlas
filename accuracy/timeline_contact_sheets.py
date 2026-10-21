"""Render review sheets from timeline points with model boxes and labels."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TIMELINE = ROOT / "data" / "timeline_camera_v1.json"
OUT = ROOT / "research" / "event_timeline" / "contact_sheets"
W, H, LABEL_H = 560, 420, 54

SHEETS = {
    "01_north_opening.jpg": [("north", t) for t in (0, 60, 120, 180, 240, 300, 360, 420)],
    "02_north_midday.jpg": [("north", t) for t in (480, 540, 600, 660, 720, 780, 840, 900)],
    "03_north_peak.jpg": [("north", t) for t in (960, 1080, 1200, 1320, 1440, 1560, 1680, 1800)],
    "04_north_tail.jpg": [("north", t) for t in (1920, 2040, 2160, 2280, 2400, 2520, 2580, 2640)],
    "05_south_opening.jpg": [("south", t) for t in (0, 300, 600, 900, 1200, 1500, 1800, 2100)],
    "06_south_midday.jpg": [("south", t) for t in (2160, 2220, 2280, 2340, 2400, 2460, 2520, 2580)],
    "07_south_peak.jpg": [("south", t) for t in (60, 180, 360, 480, 660, 780, 960, 2640)],
    "08_transitions.jpg": [
        ("north", 300),
        ("north", 600),
        ("south", 600),
        ("north", 2100),
        ("north", 2160),
        ("south", 2580),
        ("south", 2640),
        ("north", 60),
    ],
    "09_endpoint.jpg": [
        ("north", 2640),
        ("north", 2659),
        ("south", 2640),
        ("south", 2659),
    ],
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def main() -> None:
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    points = {(point["camera"], round(point["video_seconds"])): point for point in timeline["points"]}
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, selections in SHEETS.items():
        sheet = Image.new("RGB", (W * 4, (H + LABEL_H) * 2), "#071018")
        for index, key in enumerate(selections):
            point = points[key]
            source = Image.open(ROOT / point["image"]).convert("RGB")
            source = source.resize((W, H), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (W, H + LABEL_H), "#071018")
            canvas.paste(source, (0, LABEL_H))
            draw = ImageDraw.Draw(canvas)
            counts = point["counts"]
            label = (
                f"{point['camera'].upper()} {point['video_timecode']} | "
                f"total {counts['total']}  L{counts['large']} M{counts['medium']} "
                f"S{counts['small']} U{counts['unknown']}"
            )
            business = point["business_time"][11:19]
            draw.text((9, 4), label, fill="#66f2d0", font=font(17, True))
            draw.text(
                (9, 27),
                f"business {business} | frame {point['frame_number']} | review {point['review_vehicle_count']}",
                fill="#cbd5e1",
                font=font(15),
            )
            for number, vehicle in enumerate(point["vehicles"], 1):
                box = vehicle.get("bbox")
                if not isinstance(box, list) or len(box) != 4:
                    continue
                x0, y0, x1, y1 = [
                    max(0.0, min(1.0, float(value))) for value in box
                ]
                if not (x0 < x1 and y0 < y1):
                    continue
                left, top = int(x0 * W), LABEL_H + int(y0 * H)
                right, bottom = int(x1 * W), LABEL_H + int(y1 * H)
                draw.rectangle((left, top, right, bottom), outline="#ffbe3d", width=2)
                draw.text((left + 3, top + 2), str(number), fill="#fff", font=font(16, True))
            x = (index % 4) * W
            y = (index // 4) * (H + LABEL_H)
            sheet.paste(canvas, (x, y))
        sheet.save(OUT / filename, quality=92)
        print(OUT / filename)


if __name__ == "__main__":
    main()
