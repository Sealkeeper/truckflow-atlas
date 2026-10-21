"""Architecture A2: tight lane-following depth windows.

The first band attempt used wide horizontal strips. Those strips put booth walls
around the lane and caused the model to treat stacked container trailers as
background. This version follows the corridor: a tight far window is sampled at
two zoom levels with a container-row prompt, while mid/near/bottom windows use
the general compact prompt. Windows own disjoint depth cores.
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
from prompts import band_prompt, container_row_prompt


WINDOWS = [
    {
        "name": "far_b",
        "x": [0.39, 0.57],
        "y": [0.14, 0.42],
        "core": [0.00, 0.40],
        "prompt": "row",
    },
    {
        "name": "mid",
        "x": [0.32, 0.66],
        "y": [0.26, 0.68],
        "core": [0.40, 0.62],
        "prompt": "band",
    },
    {
        "name": "near",
        "x": [0.29, 0.73],
        "y": [0.50, 0.90],
        "core": [0.62, 0.85],
        "prompt": "band",
    },
    {
        "name": "bottom",
        "x": [0.26, 1.00],
        "y": [0.78, 1.00],
        "core": [0.85, 1.00],
        "prompt": "band",
    },
]


def _to_global(box: Sequence[float], window: dict[str, Any]) -> list[float]:
    x0, x1 = window["x"]
    y0, y1 = window["y"]
    return [
        x0 + box[0] * (x1 - x0),
        y0 + box[1] * (y1 - y0),
        x0 + box[2] * (x1 - x0),
        y0 + box[3] * (y1 - y0),
    ]


def _in_core(center: Sequence[float], window: dict[str, Any], tolerance: float = 0.015) -> bool:
    c0, c1 = window["core"]
    return c0 - tolerance <= center[1] <= c1 + tolerance


def run_case(
    camera: str,
    time_s: int,
    *,
    model: str = "doubao",
    force: bool = False,
    type_review: bool = True,
) -> dict[str, Any]:
    out_path = RUNS / "windows" / f"{camera}_{time_s}.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    frame = frame_path(camera, time_s)
    gold = load_gold()[(camera, time_s)]
    run_dir = EVIDENCE / "windows" / f"{camera}_{time_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    window_records: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    started = time.perf_counter()

    for window in WINDOWS:
        crop_box = [window["x"][0], window["y"][0], window["x"][1], window["y"][1]]
        crop_path = run_dir / f"window_{window['name']}.jpg"
        crop_meta = save_crop(
            frame, crop_box, crop_path, pad=0.0, long_side=1600, grid=False
        )
        prompt = (
            container_row_prompt()
            if window["prompt"] == "row"
            else band_prompt(window["name"], window["y"][0], window["y"][1], 0.0, 1.0)
        )
        call = call_model(
            prompt,
            [crop_path],
            model=model,
            stage=f"window:{window['name']}",
            max_tokens=1800,
        )
        calls.append(call)
        retried = False
        if not call.get("ok") or call.get("parsed") is None:
            retry = call_model(
                prompt,
                [crop_path],
                model=model,
                stage=f"window:{window['name']}:retry",
                max_tokens=1400,
                deadline_s=100,
            )
            calls.append(retry)
            if retry.get("ok") and retry.get("parsed") is not None:
                call = retry
                retried = True
        parsed = call.get("parsed") or {}
        accepted = 0
        rejected_edge = 0
        for raw in parsed.get("vehicles") or []:
            if raw.get("is_truck") is False:
                continue
            box = bbox_array(raw.get("bbox"))
            if box is None:
                continue
            global_box = _to_global(box, window)
            center = bbox_center(global_box)
            if not _in_core(center, window):
                rejected_edge += 1
                continue
            candidates.append(
                {
                    "bbox_local": box,
                    "bbox_global": global_box,
                    "center_global": center,
                    "size": raw.get("size", "unknown"),
                    "visible": raw.get("visible", "unknown"),
                    "cargo_color": raw.get("cargo_color"),
                    "identity_clues": raw.get("identity_clues")
                    or raw.get("distinct_from_above"),
                    "evidence": raw.get("evidence"),
                    "uncertain": bool(raw.get("uncertain")),
                    "provenance": {"window": window["name"], "stage": "window"},
                }
            )
            accepted += 1
        window_records.append(
            {
                "window": window["name"],
                "core": window["core"],
                "crop": crop_meta,
                "model_counts": parsed.get("counts"),
                "model_vehicle_list_length": len(parsed.get("vehicles") or []),
                "accepted": accepted,
                "rejected_edge": rejected_edge,
                "retried": retried,
                "call_ok": call.get("ok"),
                "scene_notes": parsed.get("notes") or parsed.get("scene_notes"),
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
        "architecture": "windows",
        "camera": camera,
        "time": time_s,
        "frame": str(frame),
        "gold": gold,
        "windows": window_records,
        "candidates": candidates,
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
            f"windows {item}: pred={result['counts']} gold={result['gold']['total']} "
            f"exact={result['metrics']['exact']} calls={result['cost']['calls']} "
            f"tokens={result['cost']['total_tokens']} wall={result['wall_s']}s"
        )


if __name__ == "__main__":
    main()
