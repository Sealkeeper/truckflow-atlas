"""Architecture A: horizontal spatial decomposition with semantic seam merging.

The frame is split into far / mid / near horizontal windows. Each window owns a
non-overlapping core band; only trucks whose visible body center falls in that
core are counted by that window. Overlap is used as visual context, not as a
second vote. Candidates that still look like duplicates across windows are sent
to a multimodal A/B adjudicator.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Sequence

from common import (
    EVIDENCE,
    RUNS,
    bbox_array,
    bbox_center,
    call_model,
    canonical_counts,
    frame_path,
    load_gold,
    save_crop,
    score,
    sum_calls,
    write_json,
)
from fusion import dedupe_candidates, review_types
from prompts import band_prompt


BANDS = [
    # Depth bands get shorter toward the vanishing point, matching the
    # perspective scale of a truck at that depth rather than a fixed 1/3 split.
    {"name": "far", "x": [0.33, 0.66], "y": [0.00, 0.28], "core": [0.00, 0.26]},
    {"name": "upper", "x": [0.30, 0.70], "y": [0.18, 0.42], "core": [0.26, 0.38]},
    {"name": "mid", "x": [0.27, 0.78], "y": [0.34, 0.68], "core": [0.38, 0.62]},
    {"name": "near", "x": [0.26, 1.00], "y": [0.56, 1.00], "core": [0.62, 1.00]},
]


def _to_global(box: Sequence[float], band: dict[str, Any]) -> list[float]:
    x0, x1 = band["x"]
    y0, y1 = band["y"]
    return [
        x0 + box[0] * (x1 - x0),
        y0 + box[1] * (y1 - y0),
        x0 + box[2] * (x1 - x0),
        y0 + box[3] * (y1 - y0),
    ]


def _in_core(center: Sequence[float], band: dict[str, Any], tolerance: float = 0.018) -> bool:
    c0, c1 = band["core"]
    return c0 - tolerance <= center[1] <= c1 + tolerance


def run_case(
    camera: str,
    time_s: int,
    *,
    model: str = "doubao",
    force: bool = False,
    type_review: bool = True,
) -> dict[str, Any]:
    out_path = RUNS / "bands" / f"{camera}_{time_s}.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    frame = frame_path(camera, time_s)
    gold = load_gold()[(camera, time_s)]
    run_dir = EVIDENCE / "bands" / f"{camera}_{time_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    band_records: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    started = time.perf_counter()

    for band in BANDS:
        crop_box = [band["x"][0], band["y"][0], band["x"][1], band["y"][1]]
        crop_path = run_dir / f"band_{band['name']}.jpg"
        crop_meta = save_crop(frame, crop_box, crop_path, pad=0.0, long_side=1500, grid=False)
        call = call_model(
            band_prompt(band["name"], band["y"][0], band["y"][1], band["core"][0], band["core"][1]),
            [crop_path],
            model=model,
            stage=f"band:{band['name']}",
            max_tokens=2200,
        )
        calls.append(call)
        parsed = call.get("parsed") or {}
        raw_vehicles = parsed.get("vehicles") or []
        accepted = 0
        rejected_edge = 0
        rejected_other = 0
        for raw in raw_vehicles:
            box = bbox_array(raw.get("bbox"))
            if box is None or raw.get("is_truck") is False:
                rejected_other += 1
                continue
            global_box = _to_global(box, band)
            center_global = bbox_center(global_box)
            if not _in_core(center_global, band):
                rejected_edge += 1
                continue
            candidates.append(
                {
                    "bbox_local": box,
                    "bbox_global": global_box,
                    "center_global": center_global,
                    "size": raw.get("size", "unknown"),
                    "visible": raw.get("visible", "unknown"),
                    "cargo_color": raw.get("cargo_color"),
                    "heading": raw.get("heading"),
                    "identity_clues": raw.get("identity_clues"),
                    "evidence": raw.get("evidence"),
                    "uncertain": bool(raw.get("uncertain")),
                    "source_band": band["name"],
                    "source_bbox": crop_box,
                }
            )
            accepted += 1
        band_records.append(
            {
                "band": band["name"],
                "crop": crop_meta,
                "model_counts": parsed.get("counts"),
                "model_vehicle_list_length": len(raw_vehicles),
                "accepted": accepted,
                "rejected_edge": rejected_edge,
                "rejected_other": rejected_other,
                "edge_vehicles": parsed.get("edge_vehicles", []),
                "scene_notes": parsed.get("scene_notes"),
            }
        )

    final_pre, adjudications, merged_into = dedupe_candidates(
        frame, candidates, run_dir, calls, model=model
    )
    counts_pre = canonical_counts(final_pre)
    if type_review:
        final, rejected = review_types(frame, final_pre, run_dir, calls, model=model)
    else:
        final, rejected = final_pre, []
    counts = canonical_counts(final)
    metrics = score(gold, counts)
    metrics_pre = score(gold, counts_pre)

    payload = {
        "architecture": "bands",
        "camera": camera,
        "time": time_s,
        "frame": str(frame),
        "gold": gold,
        "bands": band_records,
        "candidates_after_bands": candidates,
        "adjudications": adjudications,
        "final_vehicles_pre_type": final_pre,
        "final_vehicles": final,
        "final_vehicles_rejected_by_type_review": rejected,
        "counts_pre_type": counts_pre,
        "counts": counts,
        "metrics_pre_type": metrics_pre,
        "metrics": metrics,
        "calls": calls,
        "cost": sum_calls(calls),
        "wall_s": round(time.perf_counter() - started, 2),
    }
    write_json(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", default="north_300,north_600,south_600,north_1200,south_1200")
    parser.add_argument("--model", default="doubao")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-type-review", action="store_true")
    args = parser.parse_args()
    for item in args.frames.split(","):
        camera, time_text = item.strip().split("_")
        result = run_case(
            camera,
            int(time_text),
            model=args.model,
            force=args.force,
            type_review=not args.no_type_review,
        )
        print(
            f"bands {item}: pred={result['counts']} gold={result['gold']['total']} "
            f"exact={result['metrics']['exact']} calls={result['cost']['calls']} "
            f"tokens={result['cost']['total_tokens']} wall={result['wall_s']}s"
        )


if __name__ == "__main__":
    main()
