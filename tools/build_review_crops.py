"""Build fixed corridor crops used by the human-in-the-loop review modal.

The crop boxes are deliberately fixed per camera. They are for evidence
navigation only; they never decide whether two observations are the same
physical truck.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
FRAME_DIR = REPO_ROOT / "assets" / "frames"
OUTPUT_DIR = REPO_ROOT / "review" / "crops"
GOLD_PATH = REPO_ROOT / "data" / "gold" / "camera_counts_v0.json"

# (left, top, right, bottom) on the original 1280 x 960 frame.
CROP_BOXES = {
    "north": (430, 30, 900, 960),
    "south": (450, 30, 900, 960),
}


def main() -> None:
    payload = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    missing: list[str] = []

    for sample in payload["samples"]:
        camera = sample["camera"]
        time = int(sample["time"])
        source = FRAME_DIR / f"{camera}_{time}.jpg"
        if not source.exists():
            missing.append(source.name)
            continue
        with Image.open(source) as image:
            image = image.convert("RGB")
            crop = image.crop(CROP_BOXES[camera])
            crop.save(
                OUTPUT_DIR / f"{camera}_{time}.jpg",
                quality=88,
                optimize=True,
            )
        written += 1

    if missing:
        raise SystemExit(f"missing source frames: {', '.join(missing)}")
    print(f"wrote {written} corridor crops to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
