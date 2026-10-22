"""Freeze the 15-moment / 30-image review dataset as a hash manifest.

Read-only over the image files; writes one new JSON file. No network, no model calls.

    python coord/optimization-20261022/dataset/build_dataset_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "dataset-manifest-v1.json"

OLD_TIMES = [5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600]
NEW_TIMES = [177, 470, 562, 1021, 1113]
OLD_ROOT = REPO / "assets" / "frames"
NEW_ROOT = REPO / "coord" / "exploration" / "round2-research" / "independent-v1" / "raw"

LABELS = {
    5: "00:05",
    177: "02:57",
    300: "05:00",
    470: "07:50",
    562: "09:22",
    600: "10:00",
    900: "15:00",
    1021: "17:01",
    1113: "18:33",
    1200: "20:00",
    1500: "25:00",
    1800: "30:00",
    2100: "35:00",
    2400: "40:00",
    2600: "43:20",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def camera_entry(path: Path) -> dict:
    with Image.open(path) as img:
        width, height = img.size
    return {
        "path": path.relative_to(REPO).as_posix(),
        "sha256": sha256(path),
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
    }


def main() -> int:
    moments = []
    missing = []
    for t in OLD_TIMES + NEW_TIMES:
        origin = "assets/frames" if t in OLD_TIMES else "round2-independent"
        root = OLD_ROOT if t in OLD_TIMES else NEW_ROOT
        suffix = ".jpg" if t in OLD_TIMES else ".png"
        entry = {
            "moment_id": f"t{t:04d}",
            "time_s": t,
            "label": LABELS[t],
            "origin": origin,
            "cameras": {},
        }
        for cam in ("south", "north"):
            path = root / f"{cam}_{t}{suffix}"
            if not path.is_file():
                missing.append(path.as_posix())
                continue
            entry["cameras"][cam] = camera_entry(path)
        moments.append(entry)

    if missing:
        print("MISSING IMAGES:", *missing, sep="\n  ")
        return 1

    payload = {
        "schema": "truckflow-dataset-manifest-v1",
        "dataset_id": "truckflow-30img-20261022",
        "role": "development/regression (human-reviewed; not a generalisation proof)",
        "moment_count": len(moments),
        "image_count": sum(len(m["cameras"]) for m in moments),
        "moments": moments,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'moment':>8} {'label':>6} {'south':>12} {'north':>12}  origin")
    for m in moments:
        s = m["cameras"]["south"]
        n = m["cameras"]["north"]
        print(
            f"{m['moment_id']:>8} {m['label']:>6} "
            f"{s['width']}x{s['height']:>5} {n['width']}x{n['height']:>5}  {m['origin']}"
        )
    print(f"\nwrote {OUT.relative_to(REPO).as_posix()} ({len(moments)} moments, "
          f"{payload['image_count']} images)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
