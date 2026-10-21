"""Create a context crop with a visible core region.

The core rectangle is the only area whose vehicles are counted.  Pixels outside
the core are context: they let the model decide whether a partial body is a
truck and whether a tractor/trailer pair belongs together, without letting
neighbouring bands vote for the same vehicle.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def parse_box(text: str) -> tuple[float, float, float, float]:
    values = tuple(float(part) for part in text.split(","))
    if len(values) != 4:
        raise argparse.ArgumentTypeError("box must be x0,y0,x1,y1")
    x0, y0, x1, y1 = values
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise argparse.ArgumentTypeError("box must be normalized and ordered")
    return values


def expand(
    core: tuple[float, float, float, float],
    pad_x: float,
    pad_y: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, core[0] - pad_x),
        max(0.0, core[1] - pad_y),
        min(1.0, core[2] + pad_x),
        min(1.0, core[3] + pad_y),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--core", type=parse_box, required=True)
    parser.add_argument("--pad-x", type=float, default=0.04)
    parser.add_argument("--pad-y", type=float, default=0.06)
    parser.add_argument("--long-side", type=int, default=1600)
    args = parser.parse_args()

    image = Image.open(args.image).convert("RGB")
    width, height = image.size
    crop_box = expand(args.core, args.pad_x, args.pad_y)
    left = round(crop_box[0] * width)
    top = round(crop_box[1] * height)
    right = round(crop_box[2] * width)
    bottom = round(crop_box[3] * height)
    crop = image.crop((left, top, right, bottom))

    scale = args.long_side / max(crop.size)
    if scale > 1:
        crop = crop.resize(
            (round(crop.width * scale), round(crop.height * scale)),
            Image.Resampling.LANCZOS,
        )

    draw = ImageDraw.Draw(crop)
    core_px = (
        round((args.core[0] - crop_box[0]) / (crop_box[2] - crop_box[0]) * crop.width),
        round((args.core[1] - crop_box[1]) / (crop_box[3] - crop_box[1]) * crop.height),
        round((args.core[2] - crop_box[0]) / (crop_box[2] - crop_box[0]) * crop.width),
        round((args.core[3] - crop_box[1]) / (crop_box[3] - crop_box[1]) * crop.height),
    )
    line_width = max(4, round(min(crop.size) / 220))
    draw.rectangle(core_px, outline=(0, 255, 60), width=line_width)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(args.out, quality=94)
    meta = {
        "image": str(args.image.resolve()),
        "out": str(args.out.resolve()),
        "source_size": [width, height],
        "core_normalized": args.core,
        "crop_normalized": crop_box,
        "crop_pixels": [left, top, right, bottom],
        "output_size": list(crop.size),
    }
    args.out.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
