"""Build frozen auxiliary views without calling a model.

The dual-scale experiment supplies the archived aisle image plus a same-frame
far-region detail crop. No previous/future frame, user red box, count, or answer
is copied into either model input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


VM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VM_ROOT.parents[1]
EXPERIMENT = VM_ROOT / "experiments" / "dualscale_v1"
INPUTS = EXPERIMENT / "inputs"

SAMPLES = [
    "north_5",
    "south_5",
    "north_300",
    "south_300",
    "north_600",
    "south_600",
    "north_900",
    "south_900",
    "north_1200",
    "south_1200",
    "north_1500",
    "south_1500",
    "north_1800",
    "south_1800",
    "north_2100",
    "south_2100",
    "north_2400",
    "south_2400",
    "north_2600",
    "south_2600",
]

# Relative to the archived aisles. This is a same-frame detail view, not a
# temporal crop. The fixed 0..0.52 band includes the far queue and a small
# overlap below it so vehicles are less likely to be cut at the panel edge.
FAR_REGION = [0.0, 0.0, 1.0, 0.52]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    INPUTS.mkdir(parents=True, exist_ok=True)
    annotation_manifest = REPO_ROOT / "review" / "user-attachments-20261021" / "manifest.json"
    annotation_hashes = {
        item["sha256"]
        for item in json.loads(annotation_manifest.read_text(encoding="utf-8"))["records"]
    }
    rows = []
    for sample in SAMPLES:
        source = REPO_ROOT / "accuracy" / "crops" / f"{sample}_aisle.jpg"
        if not source.exists():
            raise FileNotFoundError(source)
        output = INPUTS / f"{sample}_far.jpg"
        with Image.open(source).convert("RGB") as image:
            width, height = image.size
            box = (
                round(FAR_REGION[0] * width),
                round(FAR_REGION[1] * height),
                round(FAR_REGION[2] * width),
                round(FAR_REGION[3] * height),
            )
            detail = image.crop(box)
            detail.save(output, quality=92, optimize=True)
            detail_size = list(detail.size)
        rows.append(
            {
                "sample_id": sample,
                "primary": str(source.relative_to(REPO_ROOT)).replace("\\", "/"),
                "primary_sha256": sha256(source),
                "secondary": str(output.relative_to(REPO_ROOT)).replace("\\", "/"),
                "secondary_sha256": sha256(output),
                "source_size": [width, height],
                "secondary_crop_normalized": FAR_REGION,
                "secondary_size": detail_size,
            }
        )
    input_hashes = {
        row[key] for row in rows for key in ("primary_sha256", "secondary_sha256")
    }
    if input_hashes & annotation_hashes:
        raise RuntimeError("a model input exactly matches a user red-box attachment")

    manifest = {
        "schema": "truckflow-dualscale-inputs-v1",
        "recipe": "archived aisle crop plus a fixed same-frame far-region detail crop",
        "no_temporal_or_user_annotation_input": True,
        "user_annotation_hash_match": False,
        "samples": rows,
    }
    (EXPERIMENT / "inputs.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"samples": len(rows), "far_region": FAR_REGION}, ensure_ascii=False))


if __name__ == "__main__":
    main()
