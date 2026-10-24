"""Compare one analysis job's per-camera counts with the frozen 15-moment truth.

The score is the number of exact per-frame count matches out of 30. It is a
development-set regression check, not a blind-test or generalisation score.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DEFAULT_TRUTH = (
    REPO / "coord/optimization-20261022/review_bridge/quantity-truth-15.json"
)


def camera_key(value: str) -> str:
    lowered = (value or "").lower()
    if "北" in lowered or "north" in lowered:
        return "north"
    if "南" in lowered or "south" in lowered:
        return "south"
    raise ValueError(f"unrecognised camera label: {value!r}")


def frame_count(point: dict, primary: str | None) -> int | None:
    counting = point.get("counting") or {}
    if primary:
        by_model = counting.get("counts_by_model") or {}
        if by_model.get(primary) is not None:
            return int(by_model[primary])
    total = (point.get("counts") or {}).get("total")
    return None if total is None else int(total)


def compare(job_dir: Path, truth_path: Path, primary: str | None) -> dict:
    timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    points: dict[tuple[str, int], dict] = {}
    for point in timeline:
        if point.get("aggregate"):
            continue
        camera = camera_key(str(point.get("camera")))
        time_s = int(round(float(point.get("video_time"))))
        points[(camera, time_s)] = point

    rows = []
    hits = 0
    total = 0
    for sample in truth["samples"]:
        time_s = int(sample["time"])
        for camera in ("north", "south"):
            expected = int(sample["camera_counts"][camera])
            point = points.get((camera, time_s))
            predicted = frame_count(point, primary) if point else None
            hit = predicted == expected
            hits += int(hit)
            total += 1
            rows.append({
                "time_s": time_s,
                "camera": camera,
                "predicted": predicted,
                "truth": expected,
                "hit": hit,
            })
    return {
        "schema": "truckflow-roof-count-check-v1",
        "job": job_dir.name,
        "truth": truth_path.relative_to(REPO).as_posix(),
        "primary": primary,
        "hits": hits,
        "frames": total,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path, help="job directory containing timeline.json")
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument(
        "--primary",
        default="doubao_lite",
        help="prefer this model's count; use an empty string for the merged total",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument("--fail-on-miss", action="store_true")
    args = parser.parse_args()

    report = compare(args.job.resolve(), args.truth.resolve(), args.primary or None)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for row in report["rows"]:
            mark = "OK" if row["hit"] else "MISS"
            predicted = "-" if row["predicted"] is None else row["predicted"]
            print(
                f"t={row['time_s']:<5} {row['camera']:<5} "
                f"{predicted}/{row['truth']} {mark}"
            )
        print(f"MATCH {report['hits']}/{report['frames']}")
    if args.fail_on_miss and report["hits"] != report["frames"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
