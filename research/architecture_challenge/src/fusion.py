"""Shared semantic fusion: duplicate adjudication and type review.

Bounding-box overlap is only a *proposal* mechanism. Every merge or type change
that affects the final count is backed by a multimodal model answer retained in
the run JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from common import (
    adjudication_context_image,
    bbox_center,
    call_model,
    iou,
    intersection_over_smaller,
    save_crop,
)
from prompts import adjudicate_prompt, type_review_prompt


def pair_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    box_a, box_b = a["bbox_global"], b["bbox_global"]
    overlap = iou(box_a, box_b)
    ios = intersection_over_smaller(box_a, box_b)
    dy = abs(a["center_global"][1] - b["center_global"][1])
    horiz = min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])
    horiz_ratio = horiz / max(1e-6, min(box_a[2] - box_a[0], box_b[2] - box_b[0]))
    if overlap >= 0.25 or ios >= 0.55 or (dy <= 0.05 and horiz_ratio >= 0.35):
        return max(overlap, ios, 1.0 - dy * 5)
    return 0.0


def _source_key(candidate: dict[str, Any]) -> str:
    for key in ("provenance", "source"):
        value = candidate.get(key)
        if value not in (None, "", {}):
            return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return ""


def cross_window_adjacency_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Propose adjacent pieces of one truck produced by different windows.

    A near truck cut by two windows can appear as two vertically adjacent boxes.
    Their IoU is low, so ordinary overlap rules never submit them to semantic
    adjudication. This only *proposes* the pair; the model still decides whether
    they are one physical vehicle. Stacked trailers in the same crop are not
    proposed by this rule.
    """
    if _source_key(a) == _source_key(b):
        return 0.0
    box_a, box_b = a["bbox_global"], b["bbox_global"]
    horiz = min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])
    narrower = min(box_a[2] - box_a[0], box_b[2] - box_b[0])
    horiz_ratio = horiz / max(1e-6, narrower)
    dy = abs(a["center_global"][1] - b["center_global"][1])
    height = max(box_a[3] - box_a[1], box_b[3] - box_b[1])
    if horiz_ratio >= 0.35 and dy <= max(0.16, height * 0.75):
        return 0.05 + min(0.4, horiz_ratio * 0.2)
    return 0.0


def dedupe_candidates(
    frame: Path,
    candidates: list[dict[str, Any]],
    run_dir: Path,
    calls: list[dict[str, Any]],
    *,
    model: str,
    max_pairs: int = 12,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, int]]:
    merged_into: dict[int, int] = {}
    adjudications: list[dict[str, Any]] = []
    adjudicated_pairs: set[tuple[int, int]] = set()
    # After a merge, the surviving cluster may now be adjacent to another
    # fragment. Recompute proposals until no new merge occurs, instead of
    # silently skipping every pair that touches an already merged candidate.
    for round_index in range(3):
        pairs: list[tuple[float, int, int]] = []
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                if i in merged_into or j in merged_into:
                    continue
                score = pair_score(candidates[i], candidates[j])
                if score <= 0:
                    score = cross_window_adjacency_score(candidates[i], candidates[j])
                key = (min(i, j), max(i, j))
                if score > 0 and key not in adjudicated_pairs:
                    pairs.append((score, i, j))
        pairs.sort(reverse=True)
        if not pairs:
            break

        merged_this_round = 0
        for score, i, j in pairs[:max_pairs]:
            key = (min(i, j), max(i, j))
            if i in merged_into or j in merged_into or key in adjudicated_pairs:
                continue
            adjudicated_pairs.add(key)
            pair_path = run_dir / f"pair_r{round_index}_{i:02d}_{j:02d}.jpg"
            adjudication_context_image(
                frame,
                candidates[i]["bbox_global"],
                candidates[j]["bbox_global"],
                pair_path,
            )
            call = call_model(
                adjudicate_prompt(),
                [pair_path],
                model=model,
                stage=f"adjudicate:r{round_index}:{i}-{j}",
                max_tokens=600,
            )
            calls.append(call)
            parsed = call.get("parsed") or {}
            same = parsed.get("same_vehicle")
            if same is None:
                same = score >= 0.65
                decision_source = "geometry_fallback"
            else:
                decision_source = "model"
            adjudications.append(
                {
                    "round": round_index,
                    "a": i,
                    "b": j,
                    "geometry_score": round(score, 4),
                    "same_vehicle": bool(same),
                    "confidence": parsed.get("confidence"),
                    "reason": parsed.get("reason"),
                    "decision_source": decision_source,
                    "pair_image": str(pair_path),
                    "provenance_a": candidates[i].get("provenance"),
                    "provenance_b": candidates[j].get("provenance"),
                }
            )
            if same:
                keep, drop = (i, j) if candidates[i].get("uncertain") is False else (j, i)
                merged_into[drop] = keep
                candidates[keep]["bbox_global"] = [
                    min(candidates[keep]["bbox_global"][0], candidates[drop]["bbox_global"][0]),
                    min(candidates[keep]["bbox_global"][1], candidates[drop]["bbox_global"][1]),
                    max(candidates[keep]["bbox_global"][2], candidates[drop]["bbox_global"][2]),
                    max(candidates[keep]["bbox_global"][3], candidates[drop]["bbox_global"][3]),
                ]
                candidates[keep]["center_global"] = bbox_center(
                    candidates[keep]["bbox_global"]
                )
                candidates[keep].setdefault(
                    "merged_provenance", [candidates[keep].get("provenance")]
                )
                candidates[keep]["merged_provenance"].append(
                    candidates[drop].get("provenance")
                )
                merged_this_round += 1
        if not merged_this_round:
            break

    final = [c for index, c in enumerate(candidates) if index not in merged_into]
    return final, adjudications, merged_into


def review_types(
    frame: Path,
    candidates: list[dict[str, Any]],
    run_dir: Path,
    calls: list[dict[str, Any]],
    *,
    model: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviewed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        crop_path = run_dir / f"type_{index:02d}.jpg"
        crop_meta = save_crop(
            frame,
            candidate["bbox_global"],
            crop_path,
            pad=0.012,
            long_side=900,
            grid=False,
        )
        call = call_model(
            type_review_prompt(),
            [crop_path],
            model=model,
            stage=f"type_review:{index}",
            max_tokens=500,
        )
        calls.append(call)
        parsed = call.get("parsed") or {}
        size_before = candidate.get("size", "unknown")
        size_after = parsed.get("size", size_before)
        confidence = float(parsed.get("confidence") or 0.0)
        body_kind = parsed.get("body_kind", "unknown")
        # An explicit "this is not a truck" is a gate, independent of
        # confidence. Low-confidence negatives remain visible in `rejected`
        # with needs_review=true instead of silently entering the count.
        if call.get("ok") and parsed.get("is_truck") is False:
            candidate["rejected_by_type_review"] = True
            candidate["type_review"] = {
                "size_before": size_before,
                "size_after": None,
                "confidence": confidence,
                "accepted": False,
                "needs_review": confidence < 0.8,
                "reason": parsed.get("reason"),
                "crop": crop_meta,
            }
            rejected.append(candidate)
            continue
        # Deterministic correction of the observed "all cabs are large" bias.
        if body_kind == "cab_only" and size_after == "large":
            size_after = "medium"
        if body_kind == "tractor_with_trailer" and size_after in ("medium", "small"):
            size_after = "large"
        accepted = (
            call.get("ok")
            and parsed.get("is_truck") is not False
            and size_after in ("large", "medium", "small")
            and confidence >= 0.5
        )
        if accepted:
            candidate["size"] = size_after
        candidate["type_review"] = {
            "size_before": size_before,
            "size_after": candidate.get("size", size_before),
            "confidence": confidence,
            "body_kind": body_kind,
            "has_trailer": parsed.get("has_trailer"),
            "accepted": accepted,
            "reason": parsed.get("reason"),
            "crop": crop_meta,
        }
        reviewed.append(candidate)
    return reviewed, rejected
