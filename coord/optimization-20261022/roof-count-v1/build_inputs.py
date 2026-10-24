"""Build the two model views for every frame in the frozen 15-moment dataset.

View 1 is the original full frame. View 2 is the upper 55% enlarged to at least
1280 px wide. The output manifest records source and derived-image SHA-256 so a
later run cannot silently substitute another frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from roofs import FAR_FRACTION, FAR_MIN_WIDTH, far_crop


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_DATASET = REPO / "coord/optimization-20261022/dataset/dataset-manifest-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(dataset_path: Path, output_dir: Path) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for moment in dataset["moments"]:
        for camera in ("north", "south"):
            record = moment["cameras"][camera]
            source = REPO / record["path"]
            actual = sha256(source)
            if actual != record["sha256"]:
                raise RuntimeError(f"source hash mismatch: {source.relative_to(REPO)}")
            far = output_dir / f"{camera}_{moment['time_s']}__far.jpg"
            far_crop(source, far, frac=FAR_FRACTION, min_width=FAR_MIN_WIDTH)
            samples.append({
                "sample_id": f"{camera}_{moment['time_s']}",
                "moment_id": moment["moment_id"],
                "time_s": moment["time_s"],
                "camera": camera,
                "view_1": record["path"],
                "view_1_sha256": actual,
                "view_2": far.name,
                "view_2_sha256": sha256(far),
                "coordinate_frame": "view_1",
            })
    report = {
        "schema": "truckflow-roof-count-inputs-v1",
        "scheme_id": "roof-count-v1/full+far55/lite-260915/absorb-0.55-0.15-0.02",
        "dataset_manifest": dataset_path.relative_to(REPO).as_posix(),
        "far_fraction": FAR_FRACTION,
        "far_min_width": FAR_MIN_WIDTH,
        "sample_count": len(samples),
        "samples": samples,
    }
    (output_dir / "inputs-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="frozen dataset manifest",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / ".roof-inputs",
        help="directory for derived far crops and the input manifest",
    )
    args = parser.parse_args()
    report = build(args.dataset.resolve(), args.out.resolve())
    print(json.dumps({
        "samples": report["sample_count"],
        "manifest": str(args.out / "inputs-manifest.json"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
