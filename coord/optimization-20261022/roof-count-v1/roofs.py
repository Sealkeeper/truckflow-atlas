"""Reference implementation of the adopted cargo-roof counting scheme.

The scheme has three deliberately separate layers:

1. the model returns *roof* boxes (cargo-box top, trailer top, or open top),
   grouped into vehicles, with ambiguous cab roofs parked in ``uncertain``;
2. a width-ratio absorption pass folds a narrow fragment (a second top segment
   of the same trailer) into the wide body it belongs to;
3. each surviving group is one physical cargo body, hence one vehicle.

Layer 2 needs roof boxes as input. A prompt that asks for whole-truck boxes has
already merged the fragment and body inside the model, so this post-processing
cannot repair that case.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image


# The exact recipe that produced the published development-set counts. Runs
# record this string so "which scheme ran?" is answered by evidence, not memory.
ROOF_SCHEME_ID = "roof-count-v1/full+far55/lite-260915/absorb-0.55-0.15-0.02"
ROOF_PROMPT_VERSION = "roof-count-v1"

ROOF_SYSTEM = "You are a precise freight-truck counter. Answer with JSON only."

ROOF_PROMPT = """You are counting freight trucks in one camera view of a loading yard. Use ONLY visible top surfaces, cargo-box tops, trailer tops, and visible open-top edges.

Counting rule (applies to every image):
- Count each DISTINCT visible freight cargo body exactly once: a closed box trailer, a container mounted on a chassis, a tarp-covered trailer, or an open-top trailer/cargo bed.
- Do NOT require a tractor to be visible. A cargo body with no visible tractor still counts as ONE vehicle.
- Do NOT merge two separate cargo bodies because a cab is near them.
- A tractor cab is counted only when it is clearly a standalone tractor with no visible attached cargo body.
- If you cannot tell whether a cab belongs to a cargo body, put the cab roof in "uncertain"; never count it as an extra vehicle.
- Scan the whole image, including the far end and both sides of the aisle. Far, small, dark, or partially occluded cargo bodies still count when their top or open top edge is visible.
- Exclude forklifts, cars, vans, people, equipment, stacked goods, buildings.
- Each roof_bbox must tightly bound only the visible top surface or open-top edge.
- Do not invent fully hidden vehicles.

Return JSON only:
{"roofs":[{"roof_id":"R1","roof_bbox":[x1,y1,x2,y2],"roof_kind":"cab_roof|cargo_roof|trailer_roof|top_open|unknown"}],"vehicles":[{"vehicle_id":"V1","roof_ids":["R1"],"size":"large|medium|small|unknown"}],"uncertain":[{"group_id":"U1","roof_ids":["R2"]}],"count":0}
Every roof_id must appear exactly once across vehicles and uncertain. count must equal len(vehicles).

Image 1 is the full aisle view. Image 2 is the far (upper) part of the same frame, enlarged. Count the whole aisle once. Coordinates refer to image 1 (the full view), as fractions of image 1 width/height."""


# Absorption thresholds. The uncertain branch is intentionally looser because a
# cab roof may sit farther from the cargo top it might belong to.
WIDTH_RATIO_MAX = 0.55
X_GAP_FRACTION = 0.15
Y_GAP_MAX = 0.02
UNCERTAIN_WIDTH_RATIO_MAX = 0.60
UNCERTAIN_Y_GAP_MAX = 0.06

# The far end is where a plain full-frame call undercounts, so every model call
# sends the full frame plus the upper 55% enlarged to at least 1280 px wide.
FAR_FRACTION = 0.55
FAR_MIN_WIDTH = 1280


def far_crop(
    source: str | Path,
    dest: str | Path,
    *,
    frac: float = FAR_FRACTION,
    min_width: int = FAR_MIN_WIDTH,
) -> Path:
    """Crop the upper band of a frame and enlarge it to ``min_width``."""
    target = Path(dest)
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        crop = image.crop((0, 0, width, int(height * frac)))
        ratio = min_width / crop.width if crop.width < min_width else 1.0
        if ratio > 1:
            crop = crop.resize(
                (min_width, int(crop.height * ratio)), Image.Resampling.LANCZOS
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        crop.save(target, quality=91, optimize=True)
    return target


def parse_payload(text: str) -> dict[str, Any]:
    """Parse a JSON response, tolerating a surrounding Markdown code fence."""
    cleaned = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("roof payload is not a JSON object")
    return payload


def _union(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def roots_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Group roof boxes into one root per model-side vehicle/uncertain group."""
    roofs: dict[str, list[float]] = {}
    for roof in payload.get("roofs") or []:
        try:
            roof_id = str(roof["roof_id"])
            box = [float(value) for value in roof["roof_bbox"]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(box) == 4:
            roofs[roof_id] = box

    roots: list[dict[str, Any]] = []
    used: set[str] = set()

    def group(ids: list[str], origin: str, group_id: str) -> dict[str, Any] | None:
        boxes = [roofs[roof_id] for roof_id in ids if roof_id in roofs]
        if not boxes:
            return None
        return {
            "id": group_id,
            "roof_ids": ids,
            "origin": origin,
            "size": "unknown",
            "bbox": _union(boxes),
        }

    for vehicle in payload.get("vehicles") or []:
        ids = [str(roof_id) for roof_id in vehicle.get("roof_ids") or []]
        root = group(ids, "vehicle", str(vehicle.get("vehicle_id")))
        if root:
            root["size"] = str(vehicle.get("size") or "unknown")
            roots.append(root)
            used.update(ids)
    for uncertain in payload.get("uncertain") or []:
        ids = [str(roof_id) for roof_id in uncertain.get("roof_ids") or []]
        if not ids or any(roof_id in used for roof_id in ids):
            continue
        root = group(ids, "uncertain", str(uncertain.get("group_id")))
        if root:
            roots.append(root)
            used.update(ids)
    return roots


def _width(root: dict[str, Any]) -> float:
    return root["bbox"][2] - root["bbox"][0]


def _gaps(
    first: dict[str, Any], second: dict[str, Any]
) -> tuple[float, float]:
    ax1, ay1, ax2, ay2 = first["bbox"]
    bx1, by1, bx2, by2 = second["bbox"]
    return (
        max(bx1 - ax2, ax1 - bx2, 0.0),
        max(by1 - ay2, ay1 - by2, 0.0),
    )


def absorb(roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold narrow roof fragments into the wide body they overlap."""
    units = [dict(root) for root in roots]
    while True:
        units.sort(key=lambda root: (_width(root), root["id"]))
        chosen: tuple[dict[str, Any], dict[str, Any]] | None = None
        for narrow in units:
            for wide in units:
                if wide is narrow or _width(wide) <= 0:
                    continue
                ratio = _width(narrow) / _width(wide)
                uncertain = (
                    narrow["origin"] == "uncertain"
                    or wide["origin"] == "uncertain"
                )
                ratio_max = (
                    UNCERTAIN_WIDTH_RATIO_MAX if uncertain else WIDTH_RATIO_MAX
                )
                y_max = UNCERTAIN_Y_GAP_MAX if uncertain else Y_GAP_MAX
                if ratio > ratio_max:
                    continue
                x_gap, y_gap = _gaps(narrow, wide)
                if x_gap > X_GAP_FRACTION * min(_width(narrow), _width(wide)):
                    continue
                if y_gap > y_max:
                    continue
                chosen = (narrow, wide)
                break
            if chosen:
                break
        if not chosen:
            break
        narrow, wide = chosen
        wide["bbox"] = _union([narrow["bbox"], wide["bbox"]])
        if wide.get("size") in {None, "", "unknown"}:
            wide["size"] = narrow.get("size") or "unknown"
        units.remove(narrow)
    return units


def count_units(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return ``(units after absorption, roots before absorption)``."""
    roots = roots_from_payload(payload)
    return absorb(roots), len(roots)


def unit_summary(units: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"large": 0, "medium": 0, "small": 0, "unknown": 0}
    for unit in units:
        size = unit.get("size") or "unknown"
        summary[size if size in summary else "unknown"] += 1
    return summary
