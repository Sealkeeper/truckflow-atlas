"""Core, offline evaluation primitives for round-2 truck-recognition routes.

The evaluator is deliberately strict: it never guesses a coordinate space,
never overwrites a duplicate key, and never imputes a missing label or failed
prediction. All sources are explicit paths supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


CAMERAS = ("north", "south")
OUTPUT_STATUSES = ("valid", "failed", "refused", "missing")
BBOX_SPACES = {
    "aisle_norm_0_1": "aisle normalized [0,1]",
    "full_norm_0_1": "full image normalized [0,1]",
    "aisle_int_0_1000": "aisle integer coordinates [0,1000]",
    "aisle_pixel_1040x1920": "aisle pixels 1040x1920",
    "full_pixel_1280x960": "full-image pixels 1280x960",
}
ROOF_ALLOWED_TAGS = {
    "roof",
    "cargo_roof",
    "top_edge",
    "top_polygon",
    "top_outline",
    "aerial_shape",
}
ROOF_FORBIDDEN_TAGS = {
    "plate",
    "license_plate",
    "tire",
    "wheel",
    "tail_light",
    "side_text",
    "cab_front",
    "connection",
    "trailer_hitch",
    "body_side",
}


class EvaluationError(ValueError):
    """Raised for a contract violation that must not be silently repaired."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise EvaluationError(f"{path}: top-level JSON must be an object")
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(data)


def nearest_rank_p95(values: Iterable[float | int]) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_nonnegative_int(value: Any, field: str) -> int:
    if not _is_int(value) or value < 0:
        raise EvaluationError(f"{field}: expected non-negative integer, got {value!r}")
    return value


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _format_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "未测"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def truth_map(
    path: Path, split: str = "dev"
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    """Load explicit camera and time truths without converting absence to zero."""

    doc = load_json(path)
    samples = doc.get("samples")
    if not isinstance(samples, list) or not samples:
        raise EvaluationError(f"{path}: samples must be a non-empty list")

    camera_truth: dict[str, dict[str, Any]] = {}
    time_truth: dict[int, dict[str, Any]] = {}
    seen_times: set[int] = set()
    formula_errors: list[dict[str, Any]] = []
    incomplete_camera_slots: list[str] = []
    incomplete_time_slots: list[int] = []

    for sample in samples:
        if not isinstance(sample, dict):
            raise EvaluationError(f"{path}: each sample must be an object")
        time_value = sample.get("time")
        if not _is_int(time_value) or time_value < 0:
            raise EvaluationError(f"{path}: invalid sample time {time_value!r}")
        time_s = int(time_value)
        if time_s in seen_times:
            raise EvaluationError(f"{path}: duplicate time {time_s}")
        seen_times.add(time_s)

        counts = sample.get("camera_counts")
        if not isinstance(counts, dict):
            counts = {}
        completed = sample.get("completed") is not False
        for camera in CAMERAS:
            value = counts.get(camera)
            label: int | None
            if completed and _is_int(value) and value >= 0:
                label = int(value)
            else:
                label = None
                incomplete_camera_slots.append(f"{camera}_{time_s}")
            camera_truth[f"{camera}_{time_s}"] = {
                "sample_id": f"{camera}_{time_s}",
                "camera": camera,
                "time": time_s,
                "value": label,
                "completed": completed,
            }

        overlap_value = sample.get("overlap")
        unique_value = sample.get("unique_total")
        if unique_value is None and sample.get("total") is not None:
            unique_value = sample.get("total")
        overlap = (
            int(overlap_value)
            if completed and _is_int(overlap_value) and overlap_value >= 0
            else None
        )
        unique = (
            int(unique_value)
            if completed and _is_int(unique_value) and unique_value >= 0
            else None
        )
        if overlap is None or unique is None:
            incomplete_time_slots.append(time_s)

        north = camera_truth[f"north_{time_s}"]["value"]
        south = camera_truth[f"south_{time_s}"]["value"]
        formula_unique = (
            north + south - overlap
            if north is not None and south is not None and overlap is not None
            else None
        )
        if formula_unique is not None and unique is not None and formula_unique != unique:
            formula_errors.append(
                {
                    "time": time_s,
                    "north": north,
                    "south": south,
                    "overlap": overlap,
                    "unique_total": unique,
                    "north_plus_south_minus_overlap": formula_unique,
                }
            )
        time_truth[time_s] = {
            "time": time_s,
            "north": north,
            "south": south,
            "overlap": overlap,
            "unique": unique,
            "formula_unique": formula_unique,
        }

    source_bytes = path.read_bytes()
    canonical_truth = [
        {
            "time": time_s,
            "north": value["north"],
            "south": value["south"],
            "overlap": value["overlap"],
            "unique": value["unique"],
        }
        for time_s, value in sorted(time_truth.items())
    ]
    metadata = {
        "path": str(path.resolve()),
        "split": split,
        "declared_schema": doc.get("schema"),
        "complete_declared": doc.get("complete"),
        "working_tree_sha256": sha256_bytes(source_bytes),
        "canonical_label_sha256": canonical_json_sha256(canonical_truth),
        "n_camera_slots": len(camera_truth),
        "camera_labels_present": sum(
            1 for row in camera_truth.values() if row["value"] is not None
        ),
        "incomplete_camera_slots": incomplete_camera_slots,
        "n_times": len(time_truth),
        "overlap_labels_present": sum(
            1 for row in time_truth.values() if row["overlap"] is not None
        ),
        "unique_labels_present": sum(
            1 for row in time_truth.values() if row["unique"] is not None
        ),
        "incomplete_time_slots": incomplete_time_slots,
        "truth_formula_errors": formula_errors,
        "truth_formula_valid": not formula_errors,
    }
    return camera_truth, time_truth, metadata


def normalize_bbox(
    bbox: Any, bbox_space: str
) -> tuple[list[float] | None, list[float] | None, str | None]:
    """Return (original, full-image normalized x1,y1,x2,y2, error)."""

    if not isinstance(bbox, list) or len(bbox) != 4 or not all(
        _is_number(value) for value in bbox
    ):
        return None, None, "bbox must be four numeric values"
    original = [float(value) for value in bbox]
    if not all(math.isfinite(value) for value in original):
        return original, None, "bbox contains non-finite value"
    if bbox_space not in BBOX_SPACES:
        return original, None, f"unknown bbox_space {bbox_space!r}"

    if bbox_space == "aisle_norm_0_1":
        if not all(0.0 <= value <= 1.0 for value in original):
            return original, None, "bbox outside aisle_norm_0_1"
        u1, v1, u2, v2 = original
        x1, y1 = 350.0 + 520.0 * u1, 960.0 * v1
        x2, y2 = 350.0 + 520.0 * u2, 960.0 * v2
    elif bbox_space == "full_norm_0_1":
        if not all(0.0 <= value <= 1.0 for value in original):
            return original, None, "bbox outside full_norm_0_1"
        x1, y1, x2, y2 = (
            original[0] * 1280.0,
            original[1] * 960.0,
            original[2] * 1280.0,
            original[3] * 960.0,
        )
    elif bbox_space == "aisle_int_0_1000":
        if not all(0.0 <= value <= 1000.0 for value in original):
            return original, None, "bbox outside aisle_int_0_1000"
        u1, v1, u2, v2 = (value / 1000.0 for value in original)
        x1, y1 = 350.0 + 520.0 * u1, 960.0 * v1
        x2, y2 = 350.0 + 520.0 * u2, 960.0 * v2
    elif bbox_space == "aisle_pixel_1040x1920":
        u1, v1, u2, v2 = (
            original[0] / 1040.0,
            original[1] / 1920.0,
            original[2] / 1040.0,
            original[3] / 1920.0,
        )
        if not all(0.0 <= value <= 1.0 for value in (u1, v1, u2, v2)):
            return original, None, "bbox outside aisle_pixel_1040x1920"
        x1, y1 = 350.0 + 520.0 * u1, 960.0 * v1
        x2, y2 = 350.0 + 520.0 * u2, 960.0 * v2
    else:
        if not (
            0.0 <= original[0] <= 1280.0
            and 0.0 <= original[2] <= 1280.0
            and 0.0 <= original[1] <= 960.0
            and 0.0 <= original[3] <= 960.0
        ):
            return original, None, "bbox outside full_pixel_1280x960"
        x1, y1, x2, y2 = original

    normalized = [
        x1 / 1280.0,
        y1 / 960.0,
        x2 / 1280.0,
        y2 / 960.0,
    ]
    if not (normalized[0] < normalized[2] and normalized[1] < normalized[3]):
        return original, normalized, "bbox has non-positive width or height"
    if not all(0.0 <= value <= 1.0 for value in normalized):
        return original, normalized, "mapped bbox outside full-image bounds"
    return original, normalized, None


def iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_y = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_x * inter_y
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _sample_instance_fields(sample: dict[str, Any]) -> tuple[int | None, list[Any]]:
    predicted = sample.get("predicted_count")
    if predicted is None:
        counts = sample.get("counts")
        if isinstance(counts, dict):
            predicted = counts.get("total")
    if predicted is None:
        nested = sample.get("prediction")
        if isinstance(nested, dict):
            predicted = nested.get("count")
            if predicted is None:
                nested_counts = nested.get("counts")
                if isinstance(nested_counts, dict):
                    predicted = nested_counts.get("total")

    if sample.get("evidence_scope") == "roof_only":
        vehicles = sample.get("physical_entities")
    else:
        vehicles = sample.get("vehicles")
    if vehicles is None:
        vehicles = sample.get("instances")
    if vehicles is None:
        vehicles = sample.get("objects")
    if vehicles is None:
        nested = sample.get("prediction")
        if isinstance(nested, dict):
            vehicles = nested.get("vehicles")
            if vehicles is None:
                vehicles = nested.get("instances")
    return predicted, vehicles if isinstance(vehicles, list) else []


def _polygon_bbox(polygon: Any) -> list[float] | None:
    if not isinstance(polygon, list) or len(polygon) < 3:
        return None
    points = []
    for point in polygon:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not all(_is_number(value) for value in point)
        ):
            return None
        points.append((float(point[0]), float(point[1])))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def audit_roof_only_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """Validate the roof-only evidence contract without interpreting pixels."""

    scope = sample.get("evidence_scope")
    if scope != "roof_only":
        return {
            "scope": scope or "legacy_unspecified",
            "pass": None,
            "issues": [],
            "observation_count": None,
            "physical_entity_count": None,
            "uncertain_group_count": None,
            "uncertain_observation_count": None,
            "merged_observation_count": None,
        }

    issues: list[str] = []
    observations = sample.get("roof_observations")
    entities = sample.get("physical_entities")
    if not isinstance(observations, list):
        observations = []
        issues.append("roof_only requires roof_observations list")
    if not isinstance(entities, list):
        entities = []
        issues.append("roof_only requires physical_entities list")

    observation_ids: list[str] = []
    observation_details = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            issues.append(f"roof observation #{index} is not an object")
            continue
        observation_id = observation.get("id", observation.get("observation_id"))
        if not isinstance(observation_id, str) or not observation_id:
            issues.append(f"roof observation #{index} lacks a stable ID")
        else:
            observation_ids.append(observation_id)
        top_state = observation.get("top_state")
        if top_state not in {"top_closed", "top_open", "unknown"}:
            issues.append(
                f"roof observation #{index} has invalid top_state {top_state!r}"
            )
        tags = observation.get("evidence_tags")
        if not isinstance(tags, list) or not tags:
            issues.append(f"roof observation #{index} lacks evidence_tags")
            tags = []
        normalized_tags = {
            str(tag).strip().lower().replace("-", "_") for tag in tags
        }
        forbidden = sorted(normalized_tags & ROOF_FORBIDDEN_TAGS)
        unknown_tags = sorted(normalized_tags - ROOF_ALLOWED_TAGS - ROOF_FORBIDDEN_TAGS)
        if forbidden:
            issues.append(
                f"roof observation #{index} uses non-roof evidence tags {forbidden}"
            )
        if unknown_tags:
            issues.append(
                f"roof observation #{index} uses undeclared evidence tags {unknown_tags}"
            )
        roof_bbox = observation.get("roof_bbox")
        roof_polygon = observation.get("roof_polygon")
        bbox_space = observation.get("bbox_space")
        geometry_error = None
        if roof_bbox is None and roof_polygon is None:
            geometry_error = "missing roof_bbox/roof_polygon"
        elif roof_bbox is not None:
            _, _, geometry_error = normalize_bbox(roof_bbox, bbox_space)
        else:
            polygon_bbox = _polygon_bbox(roof_polygon)
            if polygon_bbox is None:
                geometry_error = "invalid roof_polygon"
            else:
                _, _, geometry_error = normalize_bbox(polygon_bbox, bbox_space)
        if geometry_error:
            issues.append(f"roof observation #{index}: {geometry_error}")
        observation_details.append(
            {
                "id": observation_id,
                "top_state": top_state,
                "evidence_tags": sorted(normalized_tags),
                "component": observation.get("component", "unknown"),
            }
        )

    duplicate_observation_ids = sorted(
        value for value, count in Counter(observation_ids).items() if count > 1
    )
    if duplicate_observation_ids:
        issues.append(f"duplicate roof observation IDs: {duplicate_observation_ids}")

    known_observation_ids = set(observation_ids)
    referenced_observations: Counter[str] = Counter()
    entity_ids: list[str] = []
    uncertain_groups = sample.get(
        "uncertain_roof_groups", sample.get("uncertain", [])
    )
    if not isinstance(uncertain_groups, list):
        issues.append("uncertain roof groups must be a list")
        uncertain_groups = []
    uncertain_group_details = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict):
            issues.append(f"physical entity #{index} is not an object")
            continue
        entity_id = entity.get("id", entity.get("entity_id"))
        if not isinstance(entity_id, str) or not entity_id:
            issues.append(f"physical entity #{index} lacks a stable ID")
        else:
            entity_ids.append(entity_id)
        component = entity.get("component", "unknown")
        if not isinstance(component, str) or not component:
            issues.append(f"physical entity #{index} has invalid component")
        refs = entity.get("observation_ids")
        if not isinstance(refs, list) or not refs:
            issues.append(
                f"physical entity #{index} must reference at least one roof observation"
            )
            refs = []
        for ref in refs:
            if not isinstance(ref, str):
                issues.append(
                    f"physical entity #{index} has non-string observation reference"
                )
                continue
            referenced_observations[ref] += 1
            if ref not in known_observation_ids:
                issues.append(
                    f"physical entity #{index} references unknown roof observation {ref!r}"
                )
        if component in {"cab_roof", "trailer_roof", "cab", "trailer"}:
            rationale = entity.get("grouping_basis")
            if not isinstance(rationale, str) or not rationale.strip():
                issues.append(
                    f"physical entity #{index} has single-part component {component!r} "
                    "without grouping_basis"
                )
        identity_status = entity.get("identity_status", "unknown")
        if identity_status not in {"unknown", "provisional", "confirmed"}:
            issues.append(
                f"physical entity #{index} has invalid identity_status {identity_status!r}"
            )

    for index, group in enumerate(uncertain_groups):
        if not isinstance(group, dict):
            issues.append(f"uncertain roof group #{index} is not an object")
            continue
        refs = group.get("roof_ids", group.get("observation_ids"))
        if not isinstance(refs, list) or not refs:
            issues.append(
                f"uncertain roof group #{index} must reference at least one roof observation"
            )
            refs = []
        for ref in refs:
            if not isinstance(ref, str):
                issues.append(
                    f"uncertain roof group #{index} has non-string observation reference"
                )
                continue
            referenced_observations[ref] += 1
            if ref not in known_observation_ids:
                issues.append(
                    f"uncertain roof group #{index} references unknown roof observation {ref!r}"
                )
        reason = group.get("reason")
        if reason is not None and not isinstance(reason, str):
            issues.append(f"uncertain roof group #{index} has non-string reason")
        uncertain_group_details.append(
            {
                "observation_ids": refs,
                "reason": reason,
            }
        )

    duplicate_entity_ids = sorted(
        value for value, count in Counter(entity_ids).items() if count > 1
    )
    if duplicate_entity_ids:
        issues.append(f"duplicate physical entity IDs: {duplicate_entity_ids}")

    unreferenced = sorted(
        observation_id
        for observation_id in known_observation_ids
        if referenced_observations[observation_id] == 0
    )
    multiply_referenced = sorted(
        observation_id
        for observation_id, count in referenced_observations.items()
        if count > 1
    )
    if unreferenced:
        issues.append(f"roof observations not assigned to a physical entity: {unreferenced}")
    if multiply_referenced:
        issues.append(
            f"roof observations assigned to multiple physical entities: {multiply_referenced}"
        )

    if len(entities) != len(
        sample.get("physical_entities")
        if isinstance(sample.get("physical_entities"), list)
        else []
    ):
        issues.append("physical entity list is malformed")

    declared = sample.get("predicted_count")
    if not _is_int(declared) or declared != len(entities):
        issues.append(
            f"physical predicted_count {declared!r} != physical entity count {len(entities)}"
        )

    release = _release_decision(sample)
    unknowns = [
        detail["id"]
        for detail in observation_details
        if detail["top_state"] == "unknown"
        or detail["component"] == "unknown"
    ]
    if release == "auto_release" and unknowns:
        issues.append(
            f"auto-release despite unknown roof boundary/component: {unknowns}"
        )
    if release == "auto_release" and uncertain_group_details:
        issues.append("auto-release despite uncertain roof groups")
    if sample.get("review_required") is True and release == "auto_release":
        issues.append("auto-release contradicts review_required=true")

    return {
        "scope": scope,
        "pass": not issues,
        "issues": issues,
        "observation_count": len(observations),
        "physical_entity_count": len(entities),
        "uncertain_group_count": len(uncertain_group_details),
        "uncertain_observation_count": sum(
            len(group["observation_ids"])
            for group in uncertain_group_details
        ),
        "merged_observation_count": sum(
            len(refs)
            for entity in entities
            if isinstance(entity, dict)
            for refs in [entity.get("observation_ids", [])]
            if isinstance(refs, list)
        ),
        "observations": observation_details,
        "uncertain_groups": uncertain_group_details,
    }


def _sample_status(sample: dict[str, Any]) -> str:
    raw = sample.get("status")
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace("-", "_")
        aliases = {
            "ok": "valid",
            "success": "valid",
            "error": "failed",
            "invalid": "failed",
            "abstain": "refused",
            "refusal": "refused",
            "not_run": "missing",
            "not_started": "missing",
            "awaiting": "missing",
        }
        raw = aliases.get(normalized, normalized)
        if raw in OUTPUT_STATUSES:
            return raw
    if sample.get("refused") is True or sample.get("refusal") is True:
        return "refused"
    if sample.get("failure") is True or sample.get("failed") is True:
        return "failed"
    return "valid"


def _release_decision(sample: dict[str, Any]) -> str | None:
    value = sample.get("release_decision")
    if isinstance(value, bool):
        return "auto_release" if value else "review"
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {"auto_release", "release", "pass", "accepted"}:
            return "auto_release"
        if normalized in {"review", "recheck", "manual_review"}:
            return "review"
        if normalized in {"refuse", "refused", "abstain"}:
            return "refused"
    value = sample.get("auto_release")
    if isinstance(value, bool):
        return "auto_release" if value else "review"
    gate = sample.get("gate")
    if isinstance(gate, dict):
        value = gate.get("decision")
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {"auto_release", "release", "pass", "accepted"}:
            return "auto_release"
        if normalized in {"review", "recheck", "manual_review"}:
            return "review"
        if normalized in {"refuse", "refused", "abstain"}:
            return "refused"
    return None


def load_canonical_output(path: Path) -> dict[str, Any]:
    """Load the public round-2 route-output contract.

    Required sample keys are documented in ``ADAPTERS.md``. Duplicate sample
    IDs and duplicate (time, camera) pairs raise before any dictionary can
    overwrite an earlier record.
    """

    doc = load_json(path)
    raw_samples = doc.get("samples", doc.get("predictions"))
    if not isinstance(raw_samples, list):
        raise EvaluationError(f"{path}: samples/predictions must be a list")

    samples: dict[str, dict[str, Any]] = {}
    seen_camera_time: Counter[tuple[int, str]] = Counter()
    duplicate_sample_ids: list[str] = []
    duplicate_camera_times: list[dict[str, Any]] = []

    for index, sample in enumerate(raw_samples):
        if not isinstance(sample, dict):
            raise EvaluationError(f"{path}: sample #{index} must be an object")
        camera = sample.get("camera")
        time_value = sample.get("time")
        if camera not in CAMERAS:
            raise EvaluationError(f"{path}: sample #{index} has invalid camera {camera!r}")
        if not _is_int(time_value) or time_value < 0:
            raise EvaluationError(f"{path}: sample #{index} has invalid time {time_value!r}")
        time_s = int(time_value)
        sample_id = sample.get("sample_id") or f"{camera}_{time_s}"
        if not isinstance(sample_id, str) or not sample_id:
            raise EvaluationError(f"{path}: sample #{index} has invalid sample_id")
        if sample_id in samples:
            duplicate_sample_ids.append(sample_id)
        key = (time_s, camera)
        seen_camera_time[key] += 1
        if seen_camera_time[key] > 1:
            duplicate_camera_times.append({"time": time_s, "camera": camera})
            continue
        if sample_id in samples:
            continue

        status = _sample_status(sample)
        issues: list[str] = []
        predicted_raw, vehicles = _sample_instance_fields(sample)
        predicted: int | None = None
        if predicted_raw is not None:
            if _is_int(predicted_raw) and predicted_raw >= 0:
                predicted = int(predicted_raw)
            else:
                issues.append(f"predicted count is not a non-negative integer: {predicted_raw!r}")

        instance_count = len(vehicles)
        count_matches_instances = (
            predicted == instance_count if predicted is not None else None
        )
        if predicted is not None and not count_matches_instances:
            issues.append(
                f"reported count {predicted} != instance list length {instance_count}"
            )
        if status == "valid" and predicted is None:
            issues.append("valid sample has no parseable count")
        if (
            status == "valid"
            and not vehicles
            and sample.get("evidence_scope") != "roof_only"
        ):
            issues.append("valid sample has an empty/absent instance list")

        bbox_space = sample.get("bbox_space")
        ids: list[str] = []
        ids_complete = True
        boxes_normalized: list[list[float]] = []
        for instance_index, instance in enumerate(vehicles):
            if not isinstance(instance, dict):
                issues.append(f"instance #{instance_index} is not an object")
                ids_complete = False
                continue
            instance_id = instance.get("id", instance.get("instance_id"))
            if instance_id is None:
                ids_complete = False
            elif not isinstance(instance_id, str) or not instance_id:
                issues.append(f"instance #{instance_index} has invalid id")
                ids_complete = False
            else:
                ids.append(instance_id)
            instance_space = instance.get("bbox_space", bbox_space)
            bbox = instance.get("bbox")
            if bbox is not None:
                _, normalized, error = normalize_bbox(bbox, instance_space)
                if error:
                    issues.append(f"instance #{instance_index}: {error}")
                elif normalized is not None:
                    boxes_normalized.append(normalized)

        duplicate_instance_ids = sorted(
            instance_id for instance_id, count in Counter(ids).items() if count > 1
        )
        if duplicate_instance_ids:
            issues.append(f"duplicate instance IDs: {duplicate_instance_ids}")

        duplicate_boxes = []
        for left in range(len(boxes_normalized)):
            for right in range(left + 1, len(boxes_normalized)):
                score = iou(boxes_normalized[left], boxes_normalized[right])
                if score >= 0.95:
                    duplicate_boxes.append(
                        {"i": left, "j": right, "iou": round(score, 6)}
                    )

        calls_value = sample.get("call_count", sample.get("calls"))
        if isinstance(calls_value, list):
            calls = len(calls_value)
        elif _is_int(calls_value) and calls_value >= 0:
            calls = int(calls_value)
        else:
            calls = 0
        images_value = sample.get("input_images", sample.get("images"))
        if isinstance(images_value, list):
            images = len(images_value)
        elif _is_int(images_value) and images_value >= 0:
            images = int(images_value)
        else:
            images = 0
        tokens = sample.get("tokens_total", sample.get("tokens"))
        tokens = int(tokens) if _is_int(tokens) and tokens >= 0 else 0
        latency = sample.get("latency_total_s", sample.get("latency_s"))
        latency = float(latency) if _is_number(latency) and latency >= 0 else None

        if status == "valid" and issues:
            status = "failed"
        roof_audit = audit_roof_only_sample(sample)
        if roof_audit["issues"]:
            issues.extend(roof_audit["issues"])
            if status == "valid":
                status = "failed"
        samples[sample_id] = {
            "sample_id": sample_id,
            "camera": camera,
            "time": time_s,
            "status": status,
            "predicted_count": predicted,
            "instance_count": instance_count,
            "count_matches_instances": count_matches_instances,
            "ids_complete": ids_complete,
            "ids": ids,
            "duplicate_instance_ids": duplicate_instance_ids,
            "duplicate_boxes": duplicate_boxes,
            "bbox_space": bbox_space,
            "release_decision": _release_decision(sample),
            "calls": calls,
            "images": images,
            "tokens": tokens,
            "latency_s": latency,
            "issues": issues,
            "evidence_scope": sample.get("evidence_scope", "legacy_unspecified"),
            "roof_only_audit": roof_audit,
            "source_record": sample,
        }

    if duplicate_sample_ids or duplicate_camera_times:
        details = []
        if duplicate_sample_ids:
            details.append(f"duplicate sample_id(s): {sorted(set(duplicate_sample_ids))}")
        if duplicate_camera_times:
            rendered = sorted(
                {(row["time"], row["camera"]) for row in duplicate_camera_times}
            )
            details.append(f"duplicate time/camera pair(s): {rendered}")
        raise EvaluationError(f"{path}: " + "; ".join(details))

    raw_times = doc.get("times", doc.get("time_records", []))
    if not isinstance(raw_times, list):
        raise EvaluationError(f"{path}: times/time_records must be a list")
    times: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(raw_times):
        if not isinstance(record, dict) or not _is_int(record.get("time")):
            raise EvaluationError(f"{path}: time record #{index} has invalid time")
        time_s = int(record["time"])
        if time_s in times:
            raise EvaluationError(f"{path}: duplicate time record {time_s}")
        times[time_s] = dict(record)

    # Validate explicit cross-camera matches when supplied.
    for time_s, record in times.items():
        matches = record.get("matches", record.get("proposed_matches"))
        if matches is None:
            continue
        if not isinstance(matches, list):
            record.setdefault("issues", []).append("matches must be a list")
            continue
        seen_pairs: set[tuple[str, str]] = set()
        north_ids = {
            sample["ids"][index]
            for sample in (
                samples.get(f"north_{time_s}"),
            )
            if sample and sample["ids_complete"]
            for index in range(len(sample["ids"]))
        }
        south_ids = {
            sample["ids"][index]
            for sample in (
                samples.get(f"south_{time_s}"),
            )
            if sample and sample["ids_complete"]
            for index in range(len(sample["ids"]))
        }
        for pair_index, pair in enumerate(matches):
            if not isinstance(pair, dict):
                record.setdefault("issues", []).append(
                    f"match #{pair_index} is not an object"
                )
                continue
            north_id = pair.get("north_id")
            south_id = pair.get("south_id")
            key = (str(north_id), str(south_id))
            if key in seen_pairs:
                record.setdefault("issues", []).append(
                    f"duplicate north/south match {key}"
                )
            seen_pairs.add(key)
            if north_ids and north_id not in north_ids:
                record.setdefault("issues", []).append(
                    f"match references unknown north ID {north_id!r}"
                )
            if south_ids and south_id not in south_ids:
                record.setdefault("issues", []).append(
                    f"match references unknown south ID {south_id!r}"
                )
        record["validated_match_count"] = len(seen_pairs)

    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "schema": doc.get("schema"),
        "route": doc.get("route", {}),
        "dataset": doc.get("dataset", {}),
        "samples": samples,
        "times": times,
        "cost": doc.get("cost", {}),
        "workflow": doc.get("workflow", {}),
        "evidence_scope": doc.get("evidence_scope")
        or doc.get("route", {}).get("evidence_scope", "legacy_unspecified"),
        "release_unit": doc.get("release_unit", "camera"),
        "duplicate_sample_ids": duplicate_sample_ids,
        "duplicate_camera_times": duplicate_camera_times,
        "hard_errors": [
            *[f"duplicate sample_id {value}" for value in duplicate_sample_ids],
            *[
                f"duplicate time/camera {row['time']}/{row['camera']}"
                for row in duplicate_camera_times
            ],
        ],
    }


def evaluate_camera_counts(
    truth: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    counts = Counter()
    errors: list[int] = []
    error_rows: list[dict[str, Any]] = []
    under_units = over_units = under_frames = over_frames = 0
    predicted_total = truth_total = 0

    for sample_id, truth_row in truth.items():
        sample = samples.get(sample_id)
        output_status = sample["status"] if sample else "missing"
        counts[output_status] += 1
        if truth_row["value"] is None:
            counts["label_missing"] += 1
            continue
        if output_status != "valid" or sample is None:
            continue
        predicted = sample["predicted_count"]
        if predicted is None:
            counts["label_present_but_unscored"] += 1
            continue
        expected = int(truth_row["value"])
        predicted_total += predicted
        truth_total += expected
        error = predicted - expected
        errors.append(error)
        if error != 0:
            error_rows.append(
                {
                    "sample_id": sample_id,
                    "camera": truth_row["camera"],
                    "time": truth_row["time"],
                    "truth": expected,
                    "predicted": predicted,
                    "error": error,
                }
            )
        if error < 0:
            under_units += -error
            under_frames += 1
        elif error > 0:
            over_units += error
            over_frames += 1

    n_total = len(truth)
    exact = sum(1 for error in errors if error == 0)
    return {
        "n_total": n_total,
        "valid_n": counts["valid"],
        "failed": counts["failed"],
        "refused": counts["refused"],
        "missing": counts["missing"],
        "label_missing": counts["label_missing"],
        "scored_n": len(errors),
        "exact": exact,
        "headline": f"{exact}/{n_total}",
        "exact_rate": _round(exact / n_total if n_total else None),
        "mae": _round(_mean([abs(error) for error in errors])),
        "under_units": under_units,
        "over_units": over_units,
        "under_frames": under_frames,
        "over_frames": over_frames,
        "truth_total": truth_total,
        "predicted_total": predicted_total,
        "absolute_error_total": sum(abs(error) for error in errors),
        "errors": error_rows,
    }


def evaluate_times(
    truth: dict[int, dict[str, Any]],
    samples: dict[str, dict[str, Any]],
    output_times: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    metric_rows: dict[str, dict[str, Any]] = {}
    all_formula_issues: list[dict[str, Any]] = []

    for metric in ("overlap", "unique"):
        counts = Counter()
        errors: list[int] = []
        error_rows: list[dict[str, Any]] = []
        for time_s, truth_row in sorted(truth.items()):
            record = output_times.get(time_s)
            raw_status = record.get("status") if record else "missing"
            if raw_status in (None, "ok", "success"):
                status = "valid" if record else "missing"
            elif raw_status in {"invalid", "error"}:
                status = "failed"
            elif raw_status in {"abstain", "refusal"}:
                status = "refused"
            elif raw_status in OUTPUT_STATUSES:
                status = raw_status
            else:
                status = "failed"
            counts[status] += 1
            if truth_row[metric] is None:
                counts["label_missing"] += 1
                continue
            if status != "valid" or record is None:
                continue

            issues = list(record.get("issues", []))
            north_sample = samples.get(f"north_{time_s}")
            south_sample = samples.get(f"south_{time_s}")
            north = (
                north_sample["predicted_count"]
                if north_sample and north_sample["status"] == "valid"
                else None
            )
            south = (
                south_sample["predicted_count"]
                if south_sample and south_sample["status"] == "valid"
                else None
            )
            overlap = record.get("overlap")
            unique = record.get("unique", record.get("unique_total"))
            matches = record.get("matches", record.get("proposed_matches"))
            if isinstance(matches, list):
                overlap_from_matches = int(
                    record.get("validated_match_count", len(matches))
                )
                if overlap is not None and overlap != overlap_from_matches:
                    issues.append(
                        f"reported overlap {overlap} != validated match count "
                        f"{overlap_from_matches}"
                    )
                overlap = overlap_from_matches
            formula_unique = (
                north + south - overlap
                if north is not None
                and south is not None
                and _is_int(overlap)
                and overlap >= 0
                else None
            )
            if formula_unique is not None and unique is not None and unique != formula_unique:
                issues.append(
                    f"reported unique {unique} != N+S-overlap {formula_unique}"
                )
            if issues:
                status = "failed"
                record["issues"] = issues
                counts["valid"] -= 1
                counts["failed"] += 1
                counts["label_missing"] -= (
                    1 if truth_row[metric] is None else 0
                )
                all_formula_issues.append(
                    {
                        "time": time_s,
                        "metric": metric,
                        "issues": issues,
                    }
                )
                continue

            predicted = overlap if metric == "overlap" else unique
            if not _is_int(predicted) or predicted < 0:
                counts["valid"] -= 1
                counts["failed"] += 1
                all_formula_issues.append(
                    {
                        "time": time_s,
                        "metric": metric,
                        "issues": [f"{metric} is not a non-negative integer"],
                    }
                )
                continue
            expected = int(truth_row[metric])
            error = int(predicted) - expected
            errors.append(error)
            if error != 0:
                error_rows.append(
                    {
                        "time": time_s,
                        "truth": expected,
                        "predicted": int(predicted),
                        "error": error,
                    }
                )

        n_total = len(truth)
        exact = sum(1 for error in errors if error == 0)
        metric_rows[metric] = {
            "n_total": n_total,
            "valid_n": counts["valid"],
            "failed": counts["failed"],
            "refused": counts["refused"],
            "missing": counts["missing"],
            "label_missing": counts["label_missing"],
            "scored_n": len(errors),
            "exact": exact,
            "headline": f"{exact}/{n_total}",
            "exact_rate": _round(exact / n_total if n_total else None),
            "mae": _round(_mean([abs(error) for error in errors])),
            "errors": error_rows,
        }
    return metric_rows["overlap"], metric_rows["unique"], all_formula_issues


def evaluate_release(
    truth: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    released = reviewed = refused = unreported = 0
    correct = released_errors = 0
    false_release_rows: list[dict[str, Any]] = []
    caught_errors = 0
    truth_error_ids: set[str] = set()

    for sample_id, truth_row in truth.items():
        sample = samples.get(sample_id)
        if (
            sample
            and sample["status"] == "valid"
            and truth_row["value"] is not None
            and sample["predicted_count"] is not None
            and sample["predicted_count"] != truth_row["value"]
        ):
            truth_error_ids.add(sample_id)

    for sample_id, sample in samples.items():
        decision = sample["release_decision"]
        if decision is None:
            unreported += 1
            continue
        if decision == "auto_release":
            released += 1
            truth_row = truth.get(sample_id)
            if (
                sample["status"] == "valid"
                and truth_row is not None
                and truth_row["value"] is not None
                and sample["predicted_count"] is not None
            ):
                expected = truth_row["value"]
                if sample["predicted_count"] == expected:
                    correct += 1
                else:
                    released_errors += 1
                    false_release_rows.append(
                        {
                            "sample_id": sample_id,
                            "truth": expected,
                            "predicted": sample["predicted_count"],
                        }
                    )
            else:
                released_errors += 1
                false_release_rows.append(
                    {
                        "sample_id": sample_id,
                        "truth": truth_row["value"] if truth_row else None,
                        "predicted": sample["predicted_count"],
                        "reason": "released without a scorable prediction",
                    }
                )
        elif decision == "review":
            reviewed += 1
        elif decision == "refused":
            refused += 1

    for sample_id in truth_error_ids:
        sample = samples.get(sample_id)
        if sample and sample["release_decision"] == "review":
            caught_errors += 1

    n_total = len(truth)
    return {
        "n_total": n_total,
        "auto_released": released,
        "correct": correct,
        "errors": released_errors,
        "coverage": _round(released / n_total if n_total else None),
        "reviewed": reviewed,
        "review_rate": _round(reviewed / n_total if n_total else None),
        "refused": refused,
        "refusal_rate": _round(refused / n_total if n_total else None),
        "unreported": unreported,
        "false_release_rate": _round(
            released_errors / released if released else None
        ),
        "truth_error_frames": len(truth_error_ids),
        "error_frames_caught_by_review": caught_errors,
        "false_release_rows": false_release_rows,
    }


def evaluate_time_release(
    truth: dict[int, dict[str, Any]],
    output_times: dict[int, dict[str, Any]],
    samples: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    released = reviewed = refused = unreported = 0
    correct = released_errors = 0
    false_release_rows = []
    truth_error_times = 0
    caught = 0

    for time_s, truth_row in sorted(truth.items()):
        record = output_times.get(time_s, {})
        decision = _release_decision(record)
        north_sample = samples.get(f"north_{time_s}")
        south_sample = samples.get(f"south_{time_s}")
        if decision is None:
            unreported += 1
            continue

        predicted = {}
        if record.get("matches") is not None:
            predicted["overlap"] = record.get("validated_match_count")
        else:
            predicted["overlap"] = record.get("overlap")
        predicted["unique"] = record.get("unique", record.get("unique_total"))
        predicted["north"] = (
            north_sample["predicted_count"]
            if north_sample and north_sample["status"] == "valid"
            else None
        )
        predicted["south"] = (
            south_sample["predicted_count"]
            if south_sample and south_sample["status"] == "valid"
            else None
        )
        expected = {
            "north": truth_row["north"],
            "south": truth_row["south"],
            "overlap": truth_row["overlap"],
            "unique": truth_row["unique"],
        }
        scorable = all(expected[key] is not None for key in expected) and all(
            predicted[key] is not None for key in predicted
        )
        aggregate_exact = scorable and all(
            int(predicted[key]) == int(expected[key]) for key in expected
        )
        if scorable and not aggregate_exact:
            truth_error_times += 1
        if decision == "auto_release":
            released += 1
            if aggregate_exact:
                correct += 1
            else:
                released_errors += 1
                false_release_rows.append(
                    {
                        "time": time_s,
                        "truth": expected,
                        "predicted": predicted,
                    }
                )
        elif decision == "review":
            reviewed += 1
            if scorable and not aggregate_exact:
                caught += 1
        elif decision == "refused":
            refused += 1

    n_total = len(truth)
    return {
        "n_total": n_total,
        "auto_released": released,
        "correct": correct,
        "errors": released_errors,
        "coverage": _round(released / n_total if n_total else None),
        "reviewed": reviewed,
        "review_rate": _round(reviewed / n_total if n_total else None),
        "refused": refused,
        "refusal_rate": _round(refused / n_total if n_total else None),
        "unreported": unreported,
        "false_release_rate": _round(
            released_errors / released if released else None
        ),
        "truth_error_frames": truth_error_times,
        "error_frames_caught_by_review": caught,
        "false_release_rows": false_release_rows,
        "release_unit": "time",
    }


def summarize_cost(samples: dict[str, dict[str, Any]], route_cost: dict[str, Any]) -> dict[str, Any]:
    observed_latencies = [
        sample["latency_s"]
        for sample in samples.values()
        if sample["latency_s"] is not None
    ]
    observed = {
        "calls": sum(sample["calls"] for sample in samples.values()),
        "images": sum(sample["images"] for sample in samples.values()),
        "tokens": sum(sample["tokens"] for sample in samples.values()),
        "latency_s_total": _round(sum(observed_latencies), 3),
        "latency_s_mean": _round(_mean(observed_latencies), 3),
        "latency_s_p95_nearest_rank": _round(
            nearest_rank_p95(observed_latencies), 3
        ),
        "latency_samples": len(observed_latencies),
    }
    initialization = route_cost.get("initialization", {})
    if not isinstance(initialization, dict):
        initialization = {}
    online_reported = route_cost.get("online", {})
    if not isinstance(online_reported, dict):
        online_reported = {}
    init_complete = all(
        _is_number(initialization.get(field))
        for field in ("calls", "images", "tokens", "latency_s")
    )
    combined = None
    if init_complete:
        combined = {
            "calls": int(initialization["calls"]) + observed["calls"],
            "images": int(initialization["images"]) + observed["images"],
            "tokens": int(initialization["tokens"]) + observed["tokens"],
            "latency_s_total": _round(
                float(initialization["latency_s"]) + observed["latency_s_total"], 3
            ),
        }
    return {
        "online_observed": observed,
        "online_reported": online_reported,
        "initialization": initialization,
        "initialization_complete": init_complete,
        "initialization_note": route_cost.get(
            "initialization_note",
            "未提供时保持 null；不以 0 冒充免费初始化",
        ),
        "combined_online_plus_initialization": combined,
        "concurrency": route_cost.get("concurrency"),
        "peak_memory_mb": route_cost.get("peak_memory_mb"),
    }


def workflow_checks(workflow: dict[str, Any]) -> dict[str, Any]:
    required_false = (
        "human_boxes_used_as_model_input",
        "same_frame_annotations_exposed",
        "future_frames_exposed",
        "previous_count_carryover",
        "failures_skipped",
    )
    results = {}
    for field in required_false:
        value = workflow.get(field)
        results[field] = {
            "value": value,
            "pass": value is False,
            "reason": "explicit false required" if value is not False else "explicit false",
        }
    memory_scope = workflow.get("memory_retrieval_scope")
    results["memory_retrieval_scope"] = {
        "value": memory_scope,
        "pass": memory_scope in {"none", "prior_frames_only"},
    }
    results["failure_counted_in_denominator"] = {
        "value": workflow.get("failure_counted_in_denominator"),
        "pass": workflow.get("failure_counted_in_denominator") is True,
    }
    results["all_pass"] = all(result["pass"] for result in results.values())
    return results


def acceptance(
    camera: dict[str, Any],
    overlap: dict[str, Any],
    unique: dict[str, Any],
    release: dict[str, Any],
    formula_issues: list[dict[str, Any]],
    output: dict[str, Any],
    truth_meta: dict[str, Any],
    input_integrity: dict[str, Any],
    baseline_exact: int = 16,
) -> dict[str, Any]:
    workflow = workflow_checks(output.get("workflow", {}))
    hard_errors = list(output.get("hard_errors", []))
    roof_scope = output.get("evidence_scope", "legacy_unspecified")
    roof_failures = {
        sample_id: sample["roof_only_audit"]["issues"]
        for sample_id, sample in output["samples"].items()
        if sample.get("roof_only_audit", {}).get("issues")
    }
    sample_issues = {
        sample_id: sample["issues"]
        for sample_id, sample in output["samples"].items()
        if sample["issues"]
    }
    checks = {
        "no_duplicate_or_overwrite": {
            "pass": not hard_errors,
            "detail": hard_errors,
        },
        "truth_camera_labels_complete": {
            "pass": truth_meta["camera_labels_present"] == truth_meta["n_camera_slots"],
            "detail": {
                "present": truth_meta["camera_labels_present"],
                "total": truth_meta["n_camera_slots"],
            },
        },
        "all_outputs_valid": {
            "pass": (
                camera["valid_n"] == camera["n_total"]
                and camera["failed"] == 0
                and camera["refused"] == 0
                and camera["missing"] == 0
            ),
            "detail": {
                "valid": camera["valid_n"],
                "failed": camera["failed"],
                "refused": camera["refused"],
                "missing": camera["missing"],
            },
        },
        "instance_counts_consistent": {
            "pass": not sample_issues,
            "detail": sample_issues,
        },
        "cross_camera_formulas_consistent": {
            "pass": not formula_issues,
            "detail": formula_issues,
        },
        "unique_and_overlap_measured": {
            "pass": (
                overlap["scored_n"] == overlap["n_total"]
                and unique["scored_n"] == unique["n_total"]
            ),
            "detail": {
                "overlap_scored": overlap["scored_n"],
                "overlap_total": overlap["n_total"],
                "unique_scored": unique["scored_n"],
                "unique_total": unique["n_total"],
            },
        },
        "camera_not_worse_than_baseline": {
            "pass": camera["exact"] >= baseline_exact and camera["scored_n"] == camera["n_total"],
            "detail": {
                "exact": camera["exact"],
                "baseline_exact": baseline_exact,
                "total": camera["n_total"],
            },
        },
        "automatic_release_no_truth_errors": {
            "pass": release["auto_released"] > 0 and release["errors"] == 0,
            "detail": {
                "auto_released": release["auto_released"],
                "errors": release["errors"],
                "false_release_rate": release["false_release_rate"],
            },
        },
        "input_hashes_verified": {
            "pass": input_integrity.get("all_match") is True,
            "detail": input_integrity,
        },
        "workflow_audit_complete_and_clean": {
            "pass": workflow["all_pass"],
            "detail": workflow,
        },
        "roof_only_contract": {
            "pass": roof_scope != "roof_only" or not roof_failures,
            "detail": {
                "evidence_scope": roof_scope,
                "applies": roof_scope == "roof_only",
                "failures": roof_failures,
            },
        },
    }
    hard_pass = all(
        checks[name]["pass"]
        for name in (
            "no_duplicate_or_overwrite",
            "truth_camera_labels_complete",
            "all_outputs_valid",
            "instance_counts_consistent",
            "cross_camera_formulas_consistent",
            "input_hashes_verified",
            "workflow_audit_complete_and_clean",
            "roof_only_contract",
        )
    )
    research_pass = (
        hard_pass
        and checks["camera_not_worse_than_baseline"]["pass"]
        and checks["unique_and_overlap_measured"]["pass"]
        and checks["automatic_release_no_truth_errors"]["pass"]
    )
    if roof_scope != "roof_only":
        verdict = "LEGACY_REFERENCE_ONLY"
    elif not hard_pass:
        verdict = "FAIL_CONTRACT"
    elif research_pass:
        verdict = "PASS_RESEARCH"
    elif checks["camera_not_worse_than_baseline"]["pass"]:
        verdict = "RESEARCH_ONLY"
    else:
        verdict = "REJECT_FOR_NOW"
    return {
        "verdict": verdict,
        "checks": checks,
        "generalization": "not_evaluated",
        "identity_metrics": "not_measured",
        "evidence_scope": roof_scope,
        "new_roof_constraint_applies": roof_scope == "roof_only",
        "note": (
            "计数、列表长度和内部公式通过不等于框、属性、配对或身份正确；"
            "自报 confidence / checked / possible_miss 不作可靠门禁。"
            "旧整车口径不能追认为新 roof-only 结果。"
        ),
    }


def evaluate_output(
    truth_path: Path,
    output: dict[str, Any],
    split: str = "dev",
    input_integrity: dict[str, Any] | None = None,
    baseline_exact: int = 16,
) -> dict[str, Any]:
    camera_truth, time_truth, truth_meta = truth_map(truth_path, split=split)
    camera = evaluate_camera_counts(camera_truth, output["samples"])
    overlap, unique, formula_issues = evaluate_times(
        time_truth, output["samples"], output["times"]
    )
    if output.get("release_unit") == "time":
        release = evaluate_time_release(time_truth, output["times"], output["samples"])
    else:
        release = evaluate_release(camera_truth, output["samples"])
    cost = summarize_cost(output["samples"], output.get("cost", {}))
    integrity = input_integrity or {"all_match": None, "note": "not supplied"}
    gate = acceptance(
        camera,
        overlap,
        unique,
        release,
        formula_issues,
        output,
        truth_meta,
        integrity,
        baseline_exact=baseline_exact,
    )
    return {
        "schema": "round2-independent-evaluation-v1",
        "route": output.get("route"),
        "source": {
            "output_path": output.get("path"),
            "output_sha256": output.get("sha256"),
            "truth_path": truth_meta["path"],
            "truth_working_tree_sha256": truth_meta["working_tree_sha256"],
            "truth_canonical_label_sha256": truth_meta["canonical_label_sha256"],
        },
        "dataset": {
            "split": split,
            "n_camera_samples": camera["n_total"],
            "n_times": overlap["n_total"],
            "truth": truth_meta,
        },
        "camera_count": camera,
        "overlap": overlap,
        "unique": unique,
        "release": release,
        "cost": cost,
        "identity": {"status": "not measured", "reason": "no complete instance-ID gold"},
        "roof_evidence": {
            "scope": output.get("evidence_scope", "legacy_unspecified"),
            "roof_observation_count": sum(
                (
                    sample.get("roof_only_audit", {}).get("observation_count") or 0
                )
                for sample in output["samples"].values()
            ),
            "physical_entity_count": sum(
                (
                    sample.get("roof_only_audit", {}).get("physical_entity_count")
                    or 0
                )
                for sample in output["samples"].values()
            ),
            "uncertain_group_count": sum(
                (
                    sample.get("roof_only_audit", {}).get(
                        "uncertain_group_count"
                    )
                    or 0
                )
                for sample in output["samples"].values()
            ),
            "uncertain_observation_count": sum(
                (
                    sample.get("roof_only_audit", {}).get(
                        "uncertain_observation_count"
                    )
                    or 0
                )
                for sample in output["samples"].values()
            ),
            "status": (
                "not measured"
                if output.get("evidence_scope") != "roof_only"
                else "structure checked; semantic accuracy not measured"
            ),
        },
        "bbox": {"status": "not measured", "reason": "no complete per-instance bbox gold"},
        "attributes": {"status": "not measured", "reason": "no complete attribute gold"},
        "acceptance": gate,
    }


def evaluation_markdown(result: dict[str, Any]) -> str:
    camera = result["camera_count"]
    overlap = result["overlap"]
    unique = result["unique"]
    release = result["release"]
    cost = result["cost"]
    acceptance_result = result["acceptance"]
    lines = [
        "# Round 2 统一评测",
        "",
        f"- 路线：`{(result.get('route') or {}).get('id', '未标明')}`",
        f"- 数据 split：`{result['dataset']['split']}`（开发集不等于泛化）",
        f"- 证据口径：`{result['roof_evidence']['scope']}`",
        f"- 终稿判定：**{acceptance_result['verdict']}**",
        f"- 身份 / 框 / 属性：`not measured`",
        "",
        "## 固定分母",
        "",
        "| 指标 | 固定分母 | valid | failed | refused | missing | 结果 | MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| 机位计数 | {camera['n_total']} | {camera['valid_n']} | {camera['failed']} | "
        f"{camera['refused']} | {camera['missing']} | {camera['headline']} | "
        f"{_format_number(camera['mae'])} |",
        f"| 唯一数 | {unique['n_total']} | {unique['valid_n']} | {unique['failed']} | "
        f"{unique['refused']} | {unique['missing']} | {unique['headline']} | "
        f"{_format_number(unique['mae'])} |",
        f"| 重合数 | {overlap['n_total']} | {overlap['valid_n']} | {overlap['failed']} | "
        f"{overlap['refused']} | {overlap['missing']} | {overlap['headline']} | "
        f"{_format_number(overlap['mae'])} |",
        "",
        f"机位漏计/多计：{camera['under_units']} 单位 / {camera['under_frames']} 帧；"
        f"{camera['over_units']} 单位 / {camera['over_frames']} 帧。",
        "",
        "## 自动放行",
        "",
        f"放行 {release['auto_released']}，正确 {release['correct']}，错误 "
        f"{release['errors']}；复核 {release['reviewed']}，拒答 {release['refused']}。"
        f"错误帧被复核捕获 {release['error_frames_caught_by_review']}/"
        f"{release['truth_error_frames']}。",
        "",
        "## 成本",
        "",
        f"在线观测：{cost['online_observed']['calls']} 次调用、"
        f"{cost['online_observed']['images']} 张图、"
        f"{cost['online_observed']['tokens']} tokens、"
        f"均值 {_format_number(cost['online_observed']['latency_s_mean'])} 秒、"
        f"p95 {_format_number(cost['online_observed']['latency_s_p95_nearest_rank'])} 秒。",
    ]
    combined = cost["combined_online_plus_initialization"]
    if combined:
        lines.append(
            f"含历史初始化合计：{combined['calls']} 次调用、{combined['images']} 张图、"
            f"{combined['tokens']} tokens、{combined['latency_s_total']} 秒。"
        )
    else:
        lines.append("历史初始化未完整给出，合计保持 `null`。")
    lines += ["", "## 门禁", "", "| 检查 | 结果 | 说明 |", "|---|---|---|"]
    for name, check in acceptance_result["checks"].items():
        lines.append(
            f"| `{name}` | {'PASS' if check['pass'] else 'FAIL'} | "
            f"`{json.dumps(check.get('detail', check.get('value')), ensure_ascii=False)}` |"
        )
    lines += ["", acceptance_result["note"], ""]
    return "\n".join(lines)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
