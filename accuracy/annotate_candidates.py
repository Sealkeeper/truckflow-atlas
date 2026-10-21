"""Draw numbered candidate boxes on a source frame for human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()

    image = Image.open(args.image).convert("RGB")
    payload = json.loads(args.result.read_text(encoding="utf-8"))
    if "vehicles" not in payload and "runs" in payload:
        payload = payload["runs"][0]["parsed"]
    width, height = image.size
    if args.scale != 1:
        image = image.resize((width * args.scale, height * args.scale), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    label_font = font(max(18, 10 * args.scale))
    colors = [(255, 60, 60), (60, 220, 60), (60, 160, 255), (255, 200, 40), (220, 80, 255)]
    for index, vehicle in enumerate(payload.get("vehicles") or [], start=1):
        box = vehicle.get("bbox")
        if not box or len(box) != 4:
            continue
        x0, y0, x1, y1 = (round(float(v) * (width if i % 2 == 0 else height) * args.scale) for i, v in enumerate(box))
        color = colors[(index - 1) % len(colors)]
        draw.rectangle((x0, y0, x1, y1), outline=color, width=max(3, args.scale * 2))
        label = f"#{index} {vehicle.get('size', '?')}"
        bbox = draw.textbbox((0, 0), label, font=label_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle((x0, max(0, y0 - th - 8), x0 + tw + 10, max(th + 8, y0)), fill=color)
        draw.text((x0 + 5, max(0, y0 - th - 5)), label, font=label_font, fill=(0, 0, 0))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(f"{args.out} ({len(payload.get('vehicles') or [])} boxes)")


if __name__ == "__main__":
    main()
