"""Architecture B: recursive candidate tree over model-proposed regions.

Root: the model proposes occupied lane segments (no global count).
Node: the segment is cropped with lane context, upscaled, and counted.
Ownership: a node only owns trucks whose center is inside its core bbox; crop
padding is context, not a second vote.
Recursion: contradictions and model-reported suspect sub-regions spawn children.
Children supersede parent candidates inside their core, so a zoom does not
double count its parent.
Leaves feed the shared semantic duplicate adjudicator and type review.
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
    bbox_area,
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
from prompts import region_count_prompt, region_proposal_prompt


MAX_NODES = 8


def _map_box(box: Sequence[float], crop: Sequence[float]) -> list[float]:
    width = crop[2] - crop[0]
    height = crop[3] - crop[1]
    return [
        crop[0] + box[0] * width,
        crop[1] + box[1] * height,
        crop[0] + box[2] * width,
        crop[1] + box[3] * height,
    ]


def _expand_box(box: Sequence[float], pad: float) -> list[float]:
    return [
        max(0.0, box[0] - pad),
        max(0.0, box[1] - pad),
        min(1.0, box[2] + pad),
        min(1.0, box[3] + pad),
    ]


def _contains(box: Sequence[float], point: Sequence[float], pad: float = 0.01) -> bool:
    return (
        box[0] - pad <= point[0] <= box[2] + pad
        and box[1] - pad <= point[1] <= box[3] + pad
    )


def _valid_region(box: Sequence[float]) -> bool:
    return box[2] - box[0] >= 0.02 and box[3] - box[1] >= 0.02


def _count_node(
    frame: Path,
    run_dir: Path,
    region: dict[str, Any],
    crop_bbox: list[float],
    calls: list[dict[str, Any]],
    *,
    model: str,
    stage_suffix: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    node_id = region["region_id"]
    depth = int(region.get("depth", 0))
    crop_path = run_dir / f"node_{node_id}{stage_suffix}.jpg"
    crop_meta = save_crop(
        frame, crop_bbox, crop_path, pad=0.0, long_side=1400, grid=False
    )
    call = call_model(
        region_count_prompt(node_id, depth, crop_bbox, depth < 2),
        [crop_path],
        model=model,
        stage=f"region:{node_id}{stage_suffix}:d{depth}",
        max_tokens=1700,
    )
    calls.append(call)
    parsed = call.get("parsed") or {}
    owned: list[dict[str, Any]] = []
    for raw in parsed.get("vehicles") or []:
        local = bbox_array(raw.get("bbox"))
        if local is None:
            continue
        global_box = _map_box(local, crop_bbox)
        center = bbox_center(global_box)
        # Crop padding supplies context; it does not grant ownership.
        if not _contains(region["bbox"], center):
            continue
        owned.append(
            {
                "bbox_local": local,
                "bbox_global": global_box,
                "center_global": center,
                "size": raw.get("size", "unknown"),
                "visible": raw.get("visible", "unknown"),
                "cargo_color": raw.get("cargo_color"),
                "identity_clues": raw.get("identity_clues"),
                "evidence": raw.get("evidence"),
                "uncertain": bool(raw.get("uncertain")),
                "node_id": node_id,
                "depth": depth,
                "provenance": {
                    "node": node_id,
                    "depth": depth,
                    "path": region.get("path", node_id),
                    "stage": stage_suffix.lstrip("_") or "first_look",
                },
            }
        )
    node = {
        "node_id": node_id,
        "parent": region.get("parent"),
        "depth": depth,
        "proposal": region.get("proposal"),
        "core_bbox": region["bbox"],
        "crop_bbox": crop_bbox,
        "crop": crop_meta,
        "model_counts": parsed.get("counts"),
        "vehicles": owned,
        "suspect_subregions": parsed.get("suspect_subregions", []),
        "scene_notes": parsed.get("scene_notes"),
    }
    return node, owned


def run_case(
    camera: str,
    time_s: int,
    *,
    model: str = "doubao",
    force: bool = False,
    type_review: bool = True,
) -> dict[str, Any]:
    out_path = RUNS / "tree" / f"{camera}_{time_s}.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    frame = frame_path(camera, time_s)
    gold = load_gold()[(camera, time_s)]
    run_dir = EVIDENCE / "tree" / f"{camera}_{time_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    started = time.perf_counter()

    root_call = call_model(
        region_proposal_prompt(),
        [frame],
        model=model,
        stage="root_regions",
        max_tokens=1400,
    )
    calls.append(root_call)
    root_parsed = root_call.get("parsed") or {}
    regions: list[dict[str, Any]] = []
    for index, raw in enumerate(root_parsed.get("regions") or [], start=1):
        box = bbox_array(raw.get("bbox"))
        if box is None or not _valid_region(box):
            continue
        regions.append(
            {
                "region_id": str(raw.get("region_id") or f"R{index}"),
                "bbox": box,
                "lane_description": raw.get("lane_description"),
                "occupancy": raw.get("occupancy"),
                "rough_truck_count": raw.get("rough_truck_count"),
                "why": raw.get("why"),
                "search_hint": raw.get("search_hint"),
                "parent": None,
                "depth": 0,
                "proposal": "model_root",
            }
        )

    root_fallback = False
    if len(regions) < 2:
        root_fallback = True
        regions.extend(
            [
                {
                    "region_id": "FAR_FALLBACK",
                    "bbox": [0.32, 0.04, 0.68, 0.44],
                    "occupancy": "occupied",
                    "parent": None,
                    "depth": 0,
                    "proposal": "geometry_fallback",
                },
                {
                    "region_id": "NEAR_FALLBACK",
                    "bbox": [0.26, 0.52, 1.0, 1.0],
                    "occupancy": "occupied",
                    "parent": None,
                    "depth": 0,
                    "proposal": "geometry_fallback",
                },
            ]
        )

    queue = list(regions)
    nodes: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    children_of: dict[str, list[list[float]]] = {}
    while queue and len(nodes) < MAX_NODES:
        region = queue.pop(0)
        node, owned = _count_node(
            frame,
            run_dir,
            region,
            _expand_box(region["bbox"], 0.055),
            calls,
            model=model,
        )
        retried = False
        if (
            not owned
            and str(region.get("occupancy", "occupied")) in ("occupied", "uncertain")
            and region.get("rough_truck_count", 1)
        ):
            retry_node, retry_owned = _count_node(
                frame,
                run_dir,
                region,
                _expand_box(region["bbox"], 0.13),
                calls,
                model=model,
                stage_suffix="_retry",
            )
            node["retry"] = {
                "crop_bbox": retry_node["crop_bbox"],
                "crop": retry_node["crop"],
                "model_counts": retry_node["model_counts"],
                "scene_notes": retry_node["scene_notes"],
            }
            if retry_owned:
                owned = retry_owned
                retried = True
        candidates.extend(owned)
        node["vehicles"] = owned
        node["retried"] = retried

        children: list[dict[str, Any]] = []
        if region.get("depth", 0) < 2:
            crop_bbox = node["retry"]["crop_bbox"] if retried else node["crop_bbox"]
            for sub_index, raw_sub in enumerate(node.get("suspect_subregions") or [], start=1):
                local = bbox_array(raw_sub.get("bbox"))
                if local is None or bbox_area(local) < 0.003:
                    continue
                mapped = _map_box(local, crop_bbox)
                children.append(
                    {
                        "region_id": f"{region['region_id']}_S{sub_index}",
                        "bbox": _expand_box(mapped, 0.01),
                        "occupancy": "uncertain",
                        "parent": region["region_id"],
                        "depth": int(region.get("depth", 0)) + 1,
                        "proposal": "model_suspect",
                        "path": f"{region.get('path', region['region_id'])}/{region['region_id']}_S{sub_index}",
                    }
                )
        if children:
            children_of[region["region_id"]] = [child["bbox"] for child in children]
        queue.extend(children)
        node["children"] = [child["region_id"] for child in children]
        nodes.append(node)

    # A child supersedes its parent's candidates inside the child's core.
    kept: list[dict[str, Any]] = []
    for candidate in candidates:
        superseded = False
        for child_core in children_of.get(candidate["node_id"], []):
            if _contains(child_core, candidate["center_global"], pad=0.0):
                superseded = True
                break
        if not superseded:
            kept.append(candidate)

    final_pre, adjudications, merged_into = dedupe_candidates(
        frame, kept, run_dir, calls, model=model
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
        "architecture": "tree",
        "camera": camera,
        "time": time_s,
        "frame": str(frame),
        "gold": gold,
        "root_regions": root_parsed.get("regions"),
        "root_fallback": root_fallback,
        "nodes": nodes,
        "candidates_before_supersede": candidates,
        "candidates_after_supersede": kept,
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
            f"tree {item}: pred={result['counts']} gold={result['gold']['total']} "
            f"exact={result['metrics']['exact']} nodes={len(result['nodes'])} "
            f"calls={result['cost']['calls']} tokens={result['cost']['total_tokens']} wall={result['wall_s']}s"
        )


if __name__ == "__main__":
    main()
