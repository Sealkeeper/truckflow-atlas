"""Evaluate the sampled timeline against manual labels and inspect stability."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TIMELINE = ROOT / "data" / "timeline_camera_v1.json"
MANUAL = ROOT / "data" / "manual_review_v1.json"
GOLD = ROOT / "data" / "gold" / "camera_counts_v0.json"
OUT = ROOT / "data" / "timeline_evaluation_v1.json"


def series(points: list[dict[str, Any]], camera: str) -> list[dict[str, Any]]:
    return sorted(
        [point for point in points if point["camera"] == camera],
        key=lambda point: point["video_seconds"],
    )


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [row["model_total"] - row["manual_total"] for row in rows]
    absolute = [abs(error) for error in errors]
    return {
        "points": len(rows),
        "exact_matches": sum(error == 0 for error in errors),
        "exact_match_rate": round(sum(error == 0 for error in errors) / len(errors), 4),
        "mae_vehicles": round(sum(absolute) / len(absolute), 4),
        "under_count_points": sum(error < 0 for error in errors),
        "under_count_vehicles": -sum(error for error in errors if error < 0),
        "over_count_points": sum(error > 0 for error in errors),
        "over_count_vehicles": sum(error for error in errors if error > 0),
        "error_histogram": dict(sorted(Counter(errors).items())),
    }


def timestamp_summary(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "camera": point["camera"],
        "video_timecode": point["video_timecode"],
        "business_time": point["business_time"],
        "frame_number": point["frame_number"],
        "total": point["counts"]["total"],
    }


def stability(points: list[dict[str, Any]], camera: str) -> dict[str, Any]:
    camera_points = series(points, camera)
    transitions = []
    for before, after in zip(camera_points, camera_points[1:]):
        before_total = before["counts"]["total"]
        after_total = after["counts"]["total"]
        if after_total != before_total:
            transitions.append(
                {
                    "from": timestamp_summary(before),
                    "to": timestamp_summary(after),
                    "delta": after_total - before_total,
                }
            )
    runs = []
    start = 0
    for index in range(1, len(camera_points) + 1):
        if (
            index == len(camera_points)
            or camera_points[index]["counts"]["total"]
            != camera_points[start]["counts"]["total"]
        ):
            length = index - start
            if length >= 5:
                runs.append(
                    {
                        "total": camera_points[start]["counts"]["total"],
                        "points": length,
                        "from_video_timecode": camera_points[start]["video_timecode"],
                        "to_video_timecode": camera_points[index - 1]["video_timecode"],
                        "duration_seconds": (index - start - 1) * 60,
                    }
                )
            start = index
    local_dips = []
    local_spikes = []
    for before, point, after in zip(
        camera_points, camera_points[1:-1], camera_points[2:]
    ):
        total = point["counts"]["total"]
        if total < before["counts"]["total"] and total < after["counts"]["total"]:
            local_dips.append(timestamp_summary(point))
        if total > before["counts"]["total"] and total > after["counts"]["total"]:
            local_spikes.append(timestamp_summary(point))
    return {
        "transitions": transitions,
        "max_abs_adjacent_jump": max(
            [abs(transition["delta"]) for transition in transitions], default=0
        ),
        "long_constant_runs": runs,
        "local_dips": local_dips,
        "local_spikes": local_spikes,
    }


def main() -> None:
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    points = timeline["points"]
    point_map = {
        (point["camera"], round(point["video_seconds"])): point for point in points
    }

    manual_rows = []
    for record in manual["records"]:
        point = point_map[(record["camera"], round(record["video_seconds"]))]
        manual_rows.append(
            {
                **record,
                "video_timecode": point["video_timecode"],
                "business_time": point["business_time"],
                "frame_number": point["frame_number"],
                "model_total": point["counts"]["total"],
                "model_counts": point["counts"],
                "error_model_minus_manual": point["counts"]["total"] - record["manual_total"],
                "review_flags": point["review_flags"],
            }
        )

    gold_rows = []
    for record in gold["samples"]:
        key = (record["camera"], round(record["time"]))
        if key not in point_map:
            continue
        point = point_map[key]
        model = point["counts"]
        gold_counts = {
            "total": record["total"],
            "large": record["large"],
            "medium": record["medium"],
            "small": record["small"],
            "unknown": 0,
        }
        total_match = model["total"] == gold_counts["total"]
        types_match = all(
            model[type_name] == gold_counts[type_name]
            for type_name in ("large", "medium", "small", "unknown")
        )
        gold_rows.append(
            {
                "camera": record["camera"],
                "video_seconds": record["time"],
                "model_total": model["total"],
                "gold_total": gold_counts["total"],
                "total_error": model["total"] - gold_counts["total"],
                "model_counts": model,
                "gold_counts": gold_counts,
                "total_match": total_match,
                "type_counts_match": types_match,
                "all_fields_match": total_match and types_match,
            }
        )
    type_differences = {"large": 0, "medium": 0, "small": 0, "unknown": 0}
    for row in gold_rows:
        for type_name in type_differences:
            type_differences[type_name] += (
                row["model_counts"][type_name] - row["gold_counts"][type_name]
            )

    payload = {
        "version": "timeline-evaluation-v1",
        "manual_review": {
            "metrics": metrics(manual_rows),
            "per_camera": {
                camera: metrics([row for row in manual_rows if row["camera"] == camera])
                for camera in ("north", "south")
            },
            "records": manual_rows,
        },
        "gold_overlap": {
            "note": (
                "16 sampled minute points overlap the frozen development set; "
                "this is not an independent validation set"
            ),
            "metrics": metrics(
                [
                    {
                        "model_total": row["model_total"],
                        "manual_total": row["gold_total"],
                    }
                    for row in gold_rows
                ]
            ),
            "total_match": sum(row["total_match"] for row in gold_rows),
            "type_count_match": sum(row["type_counts_match"] for row in gold_rows),
            "all_fields_match": sum(row["all_fields_match"] for row in gold_rows),
            "type_count_error_totals_model_minus_gold": type_differences,
            "records": gold_rows,
        },
        "stability": {
            camera: stability(points, camera) for camera in ("north", "south")
        },
        "limits": [
            "Manual review is a single-reviewer visual pass, with 16 points reused from gold_v0.",
            "No boxes are present in the gold file, so no IoU or vehicle-level duplicate metric is claimed.",
            "A 60-second sample cannot prove that all short visits were captured.",
            "Counts from the two cameras are separate visible counts and must not be added as unique vehicles.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["manual_review"]["metrics"], ensure_ascii=False))
    print(json.dumps(payload["gold_overlap"], ensure_ascii=False)[:800])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
