"""Architecture C: lane topology + per-vehicle scene graph.

The model first describes the lane topology and queue order, then emits one node
per physical truck with lane_id, queue_index, center, heading and cargo color.
Reconstruction uses those relational fields; overlapping or same-slot nodes are
still sent to the semantic adjudicator rather than merged by geometry alone.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from common import (
    EVIDENCE,
    RUNS,
    bbox_array,
    bbox_center,
    call_model,
    canonical_counts,
    frame_path,
    load_gold,
    score,
    sum_calls,
    write_json,
)
from fusion import dedupe_candidates, review_types
from prompts import scene_graph_prompt


def _resolve_part_of(
    raw_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        vehicle_id = str(raw.get("vehicle_id") or "")
        if vehicle_id:
            by_id[vehicle_id] = raw
    kept: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for raw in raw_nodes:
        part_of = raw.get("part_of")
        if part_of and str(part_of) in by_id and str(part_of) != str(raw.get("vehicle_id")):
            parent = by_id[str(part_of)]
            parent_box = bbox_array(parent.get("bbox"))
            child_box = bbox_array(raw.get("bbox"))
            if parent_box and child_box:
                parent["bbox"] = [
                    min(parent_box[0], child_box[0]),
                    min(parent_box[1], child_box[1]),
                    max(parent_box[2], child_box[2]),
                    max(parent_box[3], child_box[3]),
                ]
            relations.append(
                {
                    "child": raw.get("vehicle_id"),
                    "part_of": part_of,
                    "reason": raw.get("evidence"),
                }
            )
            continue
        kept.append(raw)
    return kept, relations


def run_case(
    camera: str,
    time_s: int,
    *,
    model: str = "doubao",
    force: bool = False,
    type_review: bool = True,
) -> dict[str, Any]:
    out_path = RUNS / "scene_graph" / f"{camera}_{time_s}.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    frame = frame_path(camera, time_s)
    gold = load_gold()[(camera, time_s)]
    run_dir = EVIDENCE / "scene_graph" / f"{camera}_{time_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    started = time.perf_counter()

    call = call_model(
        scene_graph_prompt(),
        [frame],
        model=model,
        stage="scene_graph",
        max_tokens=2800,
    )
    calls.append(call)
    parsed = call.get("parsed") or {}
    raw_nodes = [
        node for node in (parsed.get("vehicles") or []) if isinstance(node, dict)
    ]
    kept_nodes, relations = _resolve_part_of(raw_nodes)
    candidates: list[dict[str, Any]] = []
    for raw in kept_nodes:
        if raw.get("is_truck") is False:
            continue
        box = bbox_array(raw.get("bbox"))
        if box is None:
            continue
        candidates.append(
            {
                "bbox_global": box,
                "center_global": bbox_center(box),
                "size": raw.get("size", "unknown"),
                "visible": raw.get("visible", "unknown"),
                "cargo_color": raw.get("cargo_color"),
                "heading": raw.get("heading"),
                "identity_clues": raw.get("identity_clues"),
                "evidence": raw.get("evidence"),
                "uncertain": bool(raw.get("uncertain")),
                "provenance": {
                    "vehicle_id": raw.get("vehicle_id"),
                    "lane_id": raw.get("lane_id"),
                    "queue_index": raw.get("queue_index"),
                },
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
        "architecture": "scene_graph",
        "camera": camera,
        "time": time_s,
        "frame": str(frame),
        "gold": gold,
        "lanes": parsed.get("lanes"),
        "raw_nodes": raw_nodes,
        "part_of_relations": relations,
        "scene_notes": parsed.get("scene_notes"),
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
            f"scene_graph {item}: pred={result['counts']} gold={result['gold']['total']} "
            f"exact={result['metrics']['exact']} nodes={len(result['candidates'])} "
            f"calls={result['cost']['calls']} tokens={result['cost']['total_tokens']} wall={result['wall_s']}s"
        )


if __name__ == "__main__":
    main()
