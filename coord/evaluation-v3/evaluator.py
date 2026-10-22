"""TruckFlow v3 business-accuracy evaluator.

Two primary metrics are implemented:

1. quantity_all_correct_rate: south, north, and cross-camera overlap counts
   must all be exact at the same moment. Unique count is derived.
2. identity_all_correct_rate: all overlapping vehicles are distinct, their
   same-image overlap edges match gold, and cross-camera same-vehicle pairs
   match gold. Vehicle IDs must form a complete one-to-one mapping.

Localization IoU is used only to associate predicted instances with gold
instances. It is not reported as a business-accuracy gate.

The evaluator is offline and uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_VERSION = "3.0.1"
MATCH_IOU = 0.5
CAMERAS = ("south", "north")
DECISIONS = ("auto", "review", "abstain", "invalid")


class EvalError(ValueError):
    """Raised when a document is structurally unsafe to evaluate."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise EvalError(f"{path}: top-level JSON must be an object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
        return False
    x, y, width, height = (float(item) for item in value)
    return (
        math.isfinite(x)
        and math.isfinite(y)
        and math.isfinite(width)
        and math.isfinite(height)
        and 0.0 <= x <= 1.0
        and 0.0 <= y <= 1.0
        and width > 0.0
        and height > 0.0
        # Only absorb IEEE-754 representation noise (1e-9); a visibly
        # out-of-frame box must stay invalid instead of being rounded in.
        and x + width <= 1.0 + 1e-9
        and y + height <= 1.0 + 1e-9
    )


def bbox_iou(first: Iterable[float], second: Iterable[float]) -> float:
    ax, ay, aw, ah = (float(value) for value in first)
    bx, by, bw, bh = (float(value) for value in second)
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0.0 else 0.0


def _hungarian_min(cost: list[list[float]]) -> list[int]:
    """Return row -> column minimum assignment for a rectangular matrix."""

    if not cost or not cost[0]:
        return []
    row_count = len(cost)
    column_count = len(cost[0])
    if row_count > column_count:
        transposed = [
            [cost[row][column] for row in range(row_count)]
            for column in range(column_count)
        ]
        reverse = _hungarian_min(transposed)
        result = [-1] * row_count
        for column, row in enumerate(reverse):
            if row >= 0:
                result[row] = column
        return result

    infinity = float("inf")
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)

    for row in range(1, row_count + 1):
        p[0] = row
        column0 = 0
        min_values = [infinity] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[column0] = True
            row0 = p[column0]
            delta = infinity
            column1 = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                current = cost[row0 - 1][column - 1] - u[row0] - v[column]
                if current < min_values[column]:
                    min_values[column] = current
                    way[column] = column0
                if min_values[column] < delta:
                    delta = min_values[column]
                    column1 = column
            if not math.isfinite(delta):
                raise EvalError("No finite assignment exists")
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    min_values[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break

    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if p[column] != 0:
            assignment[p[column] - 1] = column - 1
    return assignment


def one_to_one_vehicle_match(
    gold_vehicles: list[dict[str, Any]],
    predicted_vehicles: list[dict[str, Any]],
    threshold: float = MATCH_IOU,
) -> dict[str, Any]:
    """Match instances by maximum total IoU, with deterministic ID tie-breaks."""

    gold_sorted = sorted(gold_vehicles, key=lambda item: item["id"])
    pred_sorted = sorted(predicted_vehicles, key=lambda item: item["id"])
    weights = [
        [bbox_iou(gold["bbox"], predicted["bbox"]) for predicted in pred_sorted]
        for gold in gold_sorted
    ]
    if gold_sorted and pred_sorted:
        row_count = len(gold_sorted)
        column_count = len(pred_sorted)
        epsilon = 1e-10
        cost = [
            [
                -weights[row][column]
                + epsilon * ((row + 1) / (row_count + 1))
                + epsilon / (column_count + 1) * ((column + 1) / (column_count + 1))
                for column in range(column_count)
            ]
            for row in range(row_count)
        ]
        assignment = _hungarian_min(cost)
    else:
        assignment = []

    gold_to_pred: dict[str, str] = {}
    pred_to_gold: dict[str, str] = {}
    ious: dict[str, float] = {}
    for gold_index, pred_index in enumerate(assignment):
        if pred_index < 0:
            continue
        score = weights[gold_index][pred_index]
        if score + 1e-12 < threshold:
            continue
        gold_id = gold_sorted[gold_index]["id"]
        pred_id = pred_sorted[pred_index]["id"]
        gold_to_pred[gold_id] = pred_id
        pred_to_gold[pred_id] = gold_id
        ious[gold_id] = score

    return {
        "gold_to_pred": gold_to_pred,
        "pred_to_gold": pred_to_gold,
        "ious": ious,
        "tp": len(gold_to_pred),
        "fp": len(pred_sorted) - len(gold_to_pred),
        "fn": len(gold_sorted) - len(gold_to_pred),
        "complete": (
            len(gold_to_pred) == len(gold_sorted)
            and len(pred_to_gold) == len(pred_sorted)
        ),
    }


def _normalized_edge(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def _validate_edges(
    edges: Any,
    label: str,
    vehicle_camera: dict[str, str],
) -> list[tuple[str, str]]:
    if not isinstance(edges, list):
        raise EvalError(f"{label} must be an array")
    result: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, list) or len(edge) != 2 or not all(isinstance(item, str) for item in edge):
            raise EvalError(f"{label}[{index}] must contain two vehicle IDs")
        first, second = edge
        if first == second:
            raise EvalError(f"{label}[{index}] links a vehicle to itself")
        if first not in vehicle_camera or second not in vehicle_camera:
            raise EvalError(f"{label}[{index}] references an unknown vehicle")
        if vehicle_camera[first] != vehicle_camera[second]:
            raise EvalError(f"{label}[{index}] must connect vehicles in the same camera")
        normalized = _normalized_edge(first, second)
        if normalized in result:
            raise EvalError(f"{label} contains a duplicate edge")
        result.add(normalized)
    return sorted(result)


def _validate_cross_pairs(
    pairs: Any,
    label: str,
    vehicle_camera: dict[str, str],
) -> list[tuple[str, str]]:
    if not isinstance(pairs, list):
        raise EvalError(f"{label} must be an array")
    result: set[tuple[str, str]] = set()
    used_south: set[str] = set()
    used_north: set[str] = set()
    for index, pair in enumerate(pairs):
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
            raise EvalError(f"{label}[{index}] must contain two vehicle IDs")
        first, second = pair
        if first not in vehicle_camera or second not in vehicle_camera:
            raise EvalError(f"{label}[{index}] references an unknown vehicle")
        cameras = {vehicle_camera[first], vehicle_camera[second]}
        if cameras != {"south", "north"}:
            raise EvalError(f"{label}[{index}] must connect south and north")
        south_id = first if vehicle_camera[first] == "south" else second
        north_id = second if south_id == first else first
        normalized = (south_id, north_id)
        if normalized in result:
            raise EvalError(f"{label} contains a duplicate pair")
        if south_id in used_south or north_id in used_north:
            raise EvalError(f"{label} contains a repeated vehicle in cross-camera pairs")
        used_south.add(south_id)
        used_north.add(north_id)
        result.add(normalized)
    return sorted(result)


def validate_gold(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if document.get("schema") != "truckflow-gold-v3":
        raise EvalError("gold schema must be truckflow-gold-v3")
    if not isinstance(document.get("dataset_id"), str) or not document["dataset_id"]:
        raise EvalError("gold dataset_id is required")
    moments = document.get("moments")
    if not isinstance(moments, list) or not moments:
        raise EvalError("gold moments must be a non-empty array")

    by_id: dict[str, dict[str, Any]] = {}
    seen_time: dict[float, str] = {}
    for moment in moments:
        if not isinstance(moment, dict):
            raise EvalError("each gold moment must be an object")
        moment_id = moment.get("moment_id")
        if not isinstance(moment_id, str) or not moment_id:
            raise EvalError("gold moment_id is required")
        if moment_id in by_id:
            raise EvalError(f"duplicate gold moment_id: {moment_id}")
        time_s = moment.get("time_s")
        if not isinstance(time_s, (int, float)) or isinstance(time_s, bool) or not math.isfinite(float(time_s)):
            raise EvalError(f"{moment_id}: gold time_s must be a finite number")
        if float(time_s) in seen_time:
            raise EvalError(
                f"{moment_id}: duplicate gold time_s {time_s} already used by {seen_time[float(time_s)]}"
            )
        seen_time[float(time_s)] = moment_id
        by_id[moment_id] = moment
        cameras = moment.get("cameras")
        if not isinstance(cameras, dict) or set(cameras) != set(CAMERAS):
            raise EvalError(f"{moment_id}: gold cameras must be south and north")

        vehicle_camera: dict[str, str] = {}
        for camera in CAMERAS:
            camera_value = cameras[camera]
            if not isinstance(camera_value, dict) or not isinstance(camera_value.get("vehicles"), list):
                raise EvalError(f"{moment_id}/{camera}: vehicles must be an array")
            for vehicle in camera_value["vehicles"]:
                if not isinstance(vehicle, dict) or not isinstance(vehicle.get("id"), str):
                    raise EvalError(f"{moment_id}/{camera}: invalid vehicle")
                vehicle_id = vehicle["id"]
                if not vehicle_id or vehicle_id in vehicle_camera:
                    raise EvalError(f"{moment_id}: duplicate vehicle id {vehicle_id!r}")
                if not is_bbox(vehicle.get("bbox")):
                    raise EvalError(f"{moment_id}/{camera}/{vehicle_id}: invalid normalized bbox")
                vehicle_camera[vehicle_id] = camera

        quantities = moment.get("quantities")
        if not isinstance(quantities, dict) or set(quantities) != {"south", "north", "overlap", "unique"}:
            raise EvalError(f"{moment_id}: quantities must contain south/north/overlap/unique")
        truth_complete = moment.get("truth_complete")
        if not isinstance(truth_complete, dict) or set(truth_complete) != {"quantity", "identity"}:
            raise EvalError(f"{moment_id}: truth_complete must contain quantity/identity")
        if not all(isinstance(truth_complete[key], bool) for key in ("quantity", "identity")):
            raise EvalError(f"{moment_id}: truth_complete values must be booleans")

        overlap_edges = _validate_edges(moment.get("overlap_edges"), f"{moment_id}/overlap_edges", vehicle_camera)
        cross_pairs = _validate_cross_pairs(
            moment.get("cross_camera_pairs"), f"{moment_id}/cross_camera_pairs", vehicle_camera
        )

        if truth_complete["quantity"]:
            if not all(is_int(quantities.get(key)) for key in ("south", "north", "overlap", "unique")):
                raise EvalError(f"{moment_id}: complete quantity truth needs four non-negative integers")
            if quantities["unique"] != quantities["north"] + quantities["south"] - quantities["overlap"]:
                raise EvalError(f"{moment_id}: gold unique count violates north+south-overlap")
            for camera in CAMERAS:
                if quantities[camera] != len(cameras[camera]["vehicles"]):
                    raise EvalError(f"{moment_id}: gold {camera} count does not match vehicle list")

        if truth_complete["identity"]:
            # A gold may carry complete identity truth while the quantity
            # block is still blank; the overlap tally is then checked once a
            # human fills it in, not by crashing the whole evaluation.
            if is_int(quantities.get("overlap")) and quantities["overlap"] != len(cross_pairs):
                raise EvalError(f"{moment_id}: gold overlap count does not match cross-camera pairs")

    return by_id


def _camera_has_complete_objects(camera: Any) -> bool:
    return (
        isinstance(camera, dict)
        and camera.get("status") == "ok"
        and camera.get("objects_complete") is True
        and is_int(camera.get("count"))
        and isinstance(camera.get("vehicles"), list)
        and camera["count"] == len(camera["vehicles"])
        and all(
            isinstance(vehicle, dict)
            and isinstance(vehicle.get("id"), str)
            and bool(vehicle["id"])
            and is_bbox(vehicle.get("bbox"))
            for vehicle in camera["vehicles"]
        )
    )


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall <= 0.0:
        return None
    return 2.0 * precision * recall / (precision + recall)


def _prediction_structure(prediction: Any, quantities: dict[str, Any] | None = None) -> dict[str, Any]:
    """Structural validity of one prediction moment for the quantity gate.

    Matching three integers is not enough: a camera that abstained, a
    duplicate vehicle id, or a count that disagrees with the vehicle list means
    the answer is not a valid automatic answer.
    """
    problems: list[str] = []
    cameras = prediction.get("cameras") if isinstance(prediction, dict) else None
    quantities = quantities if isinstance(quantities, dict) else {}
    for camera in CAMERAS:
        value = cameras.get(camera) if isinstance(cameras, dict) else None
        if not isinstance(value, dict):
            problems.append(f"{camera}_missing_camera")
            continue
        if value.get("status") != "ok":
            problems.append(f"{camera}_status_{value.get('status')}")
        count = value.get("count")
        if not is_int(count):
            problems.append(f"{camera}_count_not_integer")
            count = None
        stated = quantities.get(camera)
        if is_int(count) and is_int(stated) and count != stated:
            # Two integer count fields in one answer must agree; otherwise the
            # quantity answer is self-contradictory.
            problems.append(f"{camera}_count_disagrees_with_quantities")
        vehicles = value.get("vehicles")
        if not isinstance(vehicles, list):
            problems.append(f"{camera}_vehicles_not_array")
            continue
        if value.get("objects_complete") is not True:
            # A quantity-only answer may carry a partial object list; only a
            # claim of completeness makes list/count agreement checkable.
            continue
        ids = [vehicle.get("id") if isinstance(vehicle, dict) else None for vehicle in vehicles]
        if any(not isinstance(identifier, str) or not identifier for identifier in ids):
            problems.append(f"{camera}_invalid_vehicle_id")
        elif len(set(ids)) != len(ids):
            problems.append(f"{camera}_duplicate_vehicle_id")
        if is_int(count) and count != len(vehicles):
            problems.append(f"{camera}_count_list_mismatch")
    return {"valid": not problems, "problems": problems}


def _quantity_for_moment(
    gold: dict[str, Any],
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    gold_quantities = gold["quantities"]
    pred_quantities = prediction.get("quantities") if isinstance(prediction, dict) else None
    if not isinstance(pred_quantities, dict):
        pred_quantities = {}

    field_exact: dict[str, bool] = {}
    field_errors: dict[str, int | None] = {}
    for field in ("south", "north", "overlap"):
        predicted = pred_quantities.get(field)
        gold_value = gold_quantities.get(field)
        exact = is_int(predicted) and is_int(gold_value) and predicted == gold_value
        field_exact[field] = exact
        field_errors[field] = (
            abs(predicted - gold_value) if is_int(predicted) and is_int(gold_value) else None
        )

    predicted_unique = pred_quantities.get("unique")
    predicted_three = [pred_quantities.get(field) for field in ("south", "north", "overlap")]
    formula_valid = (
        all(is_int(value) for value in predicted_three)
        and is_int(predicted_unique)
        and predicted_unique == predicted_three[1] + predicted_three[0] - predicted_three[2]
    )

    structure = _prediction_structure(prediction, pred_quantities)
    raw_all_correct = (
        all(field_exact.values())
        and formula_valid
        and structure["valid"]
    )
    auto = isinstance(prediction, dict) and prediction.get("decision") == "auto"
    unique_exact = (
        formula_valid
        and is_int(gold_quantities.get("unique"))
        and predicted_unique == gold_quantities["unique"]
    )
    return {
        "field_exact": field_exact,
        "field_errors": field_errors,
        "formula_valid": formula_valid,
        "unique_exact": unique_exact,
        "count_list_consistent": not any(
            problem.endswith("count_list_mismatch") for problem in structure["problems"]
        ),
        "structure": structure,
        "raw_all_correct": raw_all_correct,
        "all_correct": bool(auto and raw_all_correct),
    }


def _identity_for_moment(
    gold: dict[str, Any],
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    auto = isinstance(prediction, dict) and prediction.get("decision") == "auto"
    if not auto:
        reasons.append("not_auto")

    camera_results: dict[str, Any] = {}
    vehicle_camera: dict[str, str] = {}
    predicted_vehicles: dict[str, list[dict[str, Any]]] = {}
    cameras = prediction.get("cameras") if isinstance(prediction, dict) else None

    for camera in CAMERAS:
        gold_camera = gold["cameras"][camera]
        pred_camera = cameras.get(camera) if isinstance(cameras, dict) else None
        if not _camera_has_complete_objects(pred_camera):
            reasons.append(f"{camera}_objects_incomplete")
            pred_vehicles: list[dict[str, Any]] = []
        else:
            pred_vehicles = pred_camera["vehicles"]
            ids = [vehicle["id"] for vehicle in pred_vehicles]
            if len(ids) != len(set(ids)):
                reasons.append(f"{camera}_duplicate_predicted_id")
                pred_vehicles = []
            if is_int(pred_camera.get("count")) and pred_camera["count"] != len(pred_vehicles):
                reasons.append(f"{camera}_count_list_mismatch")
            for vehicle in pred_vehicles:
                vehicle_id = vehicle["id"]
                if vehicle_id in vehicle_camera:
                    reasons.append("duplicate_predicted_id_across_cameras")
                vehicle_camera[vehicle_id] = camera

        match = one_to_one_vehicle_match(gold_camera["vehicles"], pred_vehicles)
        camera_results[camera] = {
            "tp": match["tp"],
            "fp": match["fp"],
            "fn": match["fn"],
            "complete_mapping": match["complete"],
        }
        predicted_vehicles[camera] = pred_vehicles
        if not match["complete"]:
            reasons.append(f"{camera}_mapping_incomplete")

    basic_structure_valid = not any(
        reason.startswith("duplicate_predicted") or reason.endswith("objects_incomplete")
        for reason in reasons
    )

    # Recompute matches once with mappings retained.
    matches: dict[str, Any] = {}
    for camera in CAMERAS:
        matches[camera] = one_to_one_vehicle_match(
            gold["cameras"][camera]["vehicles"], predicted_vehicles[camera]
        )

    gold_overlap_edges = {_normalized_edge(*edge) for edge in gold["overlap_edges"]}
    predicted_overlap_mapped: set[tuple[str, str]] = set()
    try:
        predicted_edges = _validate_edges(
            prediction.get("overlap_edges") if isinstance(prediction, dict) else None,
            "predicted overlap_edges",
            vehicle_camera,
        )
    except EvalError as error:
        reasons.append(f"overlap_structure_invalid:{error}")
        predicted_edges = []
        basic_structure_valid = False

    for first, second in predicted_edges:
        camera = vehicle_camera[first]
        mapping = matches[camera]["pred_to_gold"]
        mapped_first = mapping.get(first, f"__unmatched_pred__:{camera}:{first}")
        mapped_second = mapping.get(second, f"__unmatched_pred__:{camera}:{second}")
        predicted_overlap_mapped.add(_normalized_edge(mapped_first, mapped_second))

    gold_pairs = {tuple(pair) for pair in gold["cross_camera_pairs"]}
    predicted_pairs_mapped: set[tuple[str, str]] = set()
    try:
        predicted_pairs = _validate_cross_pairs(
            prediction.get("cross_camera_pairs") if isinstance(prediction, dict) else None,
            "predicted cross_camera_pairs",
            vehicle_camera,
        )
    except EvalError as error:
        reasons.append(f"cross_pair_structure_invalid:{error}")
        predicted_pairs = []
        basic_structure_valid = False

    for south_id, north_id in predicted_pairs:
        mapped_south = matches["south"]["pred_to_gold"].get(
            south_id, f"__unmatched_pred__:south:{south_id}"
        )
        mapped_north = matches["north"]["pred_to_gold"].get(
            north_id, f"__unmatched_pred__:north:{north_id}"
        )
        predicted_pairs_mapped.add((mapped_south, mapped_north))

    overlap_tp = len(gold_overlap_edges & predicted_overlap_mapped)
    cross_tp = len(gold_pairs & predicted_pairs_mapped)
    overlap_precision = _safe_rate(overlap_tp, len(predicted_overlap_mapped))
    overlap_recall = _safe_rate(overlap_tp, len(gold_overlap_edges))
    cross_precision = _safe_rate(cross_tp, len(predicted_pairs_mapped))
    cross_recall = _safe_rate(cross_tp, len(gold_pairs))

    raw_identity = (
        basic_structure_valid
        and all(result["complete_mapping"] for result in camera_results.values())
        and predicted_overlap_mapped == gold_overlap_edges
        and predicted_pairs_mapped == gold_pairs
    )
    return {
        "camera_matches": camera_results,
        "overlap_edges": {
            "tp": overlap_tp,
            "fp": len(predicted_overlap_mapped) - overlap_tp,
            "fn": len(gold_overlap_edges) - overlap_tp,
            "precision": overlap_precision,
            "recall": overlap_recall,
            "f1": _f1(overlap_precision, overlap_recall),
            "false_merge_rate": _safe_rate(len(predicted_overlap_mapped) - overlap_tp, len(predicted_overlap_mapped)),
            "exact": predicted_overlap_mapped == gold_overlap_edges,
        },
        "cross_camera_pairs": {
            "tp": cross_tp,
            "fp": len(predicted_pairs_mapped) - cross_tp,
            "fn": len(gold_pairs) - cross_tp,
            "precision": cross_precision,
            "recall": cross_recall,
            "f1": _f1(cross_precision, cross_recall),
            "false_merge_rate": _safe_rate(len(predicted_pairs_mapped) - cross_tp, len(predicted_pairs_mapped)),
            "exact": predicted_pairs_mapped == gold_pairs,
        },
        "raw_all_correct": raw_identity,
        "all_correct": bool(auto and raw_identity),
        "reasons": sorted(set(reasons)),
    }


def evaluate(gold_document: dict[str, Any], prediction_document: dict[str, Any]) -> dict[str, Any]:
    gold_moments = validate_gold(gold_document)
    if prediction_document.get("schema") != "truckflow-predictions-v3":
        raise EvalError("predictions schema must be truckflow-predictions-v3")
    if prediction_document.get("dataset_id") != gold_document.get("dataset_id"):
        raise EvalError("gold and predictions dataset_id must match")
    predicted_moments = prediction_document.get("moments")
    if not isinstance(predicted_moments, list):
        raise EvalError("predictions moments must be an array")

    prediction_by_id: dict[str, dict[str, Any]] = {}
    for moment in predicted_moments:
        if not isinstance(moment, dict) or not isinstance(moment.get("moment_id"), str):
            raise EvalError("each prediction moment needs moment_id")
        moment_id = moment["moment_id"]
        if moment_id in prediction_by_id:
            raise EvalError(f"duplicate prediction moment_id: {moment_id}")
        if moment.get("decision") not in DECISIONS:
            raise EvalError(f"{moment_id}: invalid decision")
        prediction_by_id[moment_id] = moment

    rows: list[dict[str, Any]] = []
    quantity_numerator = 0
    quantity_denominator = 0
    identity_numerator = 0
    identity_denominator = 0
    combined_numerator = 0
    combined_denominator = 0
    field_correct = {"south": 0, "north": 0, "overlap": 0}
    field_mae_sum = {"south": 0.0, "north": 0.0, "overlap": 0.0}
    field_mae_count = {"south": 0, "north": 0, "overlap": 0}
    overlap_tp = overlap_fp = overlap_fn = 0
    cross_tp = cross_fp = cross_fn = 0

    for moment_id, gold in gold_moments.items():
        prediction = prediction_by_id.get(moment_id)
        quantity_eligible = gold["truth_complete"]["quantity"] is True
        identity_eligible = gold["truth_complete"]["identity"] is True
        quantity = _quantity_for_moment(gold, prediction)
        identity = _identity_for_moment(gold, prediction)
        combined_correct = quantity["all_correct"] and identity["all_correct"]

        if quantity_eligible:
            quantity_denominator += 1
            quantity_numerator += int(quantity["all_correct"])
            for field in field_correct:
                field_correct[field] += int(quantity["field_exact"][field])
                error = quantity["field_errors"][field]
                if error is not None:
                    field_mae_sum[field] += error
                    field_mae_count[field] += 1
        if identity_eligible:
            identity_denominator += 1
            identity_numerator += int(identity["all_correct"])
            overlap_tp += identity["overlap_edges"]["tp"]
            overlap_fp += identity["overlap_edges"]["fp"]
            overlap_fn += identity["overlap_edges"]["fn"]
            cross_tp += identity["cross_camera_pairs"]["tp"]
            cross_fp += identity["cross_camera_pairs"]["fp"]
            cross_fn += identity["cross_camera_pairs"]["fn"]
        if quantity_eligible and identity_eligible:
            combined_denominator += 1
            combined_numerator += int(combined_correct)

        reasons = []
        if not quantity["all_correct"]:
            reasons.append("quantity_failed")
        if not identity["all_correct"]:
            reasons.extend(identity["reasons"] or ["identity_failed"])
        rows.append(
            {
                "moment_id": moment_id,
                "time_s": gold.get("time_s"),
                "quantity_eligible": quantity_eligible,
                "identity_eligible": identity_eligible,
                "decision": prediction.get("decision") if isinstance(prediction, dict) else "missing",
                "quantity": quantity,
                "identity": identity,
                "combined_all_correct": combined_correct,
                "reasons": sorted(set(reasons)),
            }
        )

    overlap_precision = _safe_rate(overlap_tp, overlap_tp + overlap_fp)
    overlap_recall = _safe_rate(overlap_tp, overlap_tp + overlap_fn)
    cross_precision = _safe_rate(cross_tp, cross_tp + cross_fp)
    cross_recall = _safe_rate(cross_tp, cross_tp + cross_fn)
    field_rates = {
        field: _safe_rate(field_correct[field], quantity_denominator)
        for field in field_correct
    }
    diagnostic_mean = (
        sum(rate for rate in field_rates.values() if rate is not None) / 3
        if all(rate is not None for rate in field_rates.values())
        else None
    )

    decisions = {"auto": 0, "review": 0, "abstain": 0, "invalid": 0, "missing": 0}
    for moment_id in gold_moments:
        prediction = prediction_by_id.get(moment_id)
        decision = prediction.get("decision") if isinstance(prediction, dict) else "missing"
        decisions[decision if decision in decisions else "invalid"] += 1

    return {
        "schema": "truckflow-eval-report-v3",
        "protocol_version": PROTOCOL_VERSION,
        "dataset_id": gold_document.get("dataset_id"),
        "split": gold_document.get("split"),
        "match_iou": MATCH_IOU,
        "primary_metrics": {
            "quantity_all_correct_rate": {
                "numerator": quantity_numerator,
                "denominator": quantity_denominator,
                "rate": _safe_rate(quantity_numerator, quantity_denominator),
                "diagnostics": {
                    "south_exact_rate": field_rates["south"],
                    "north_exact_rate": field_rates["north"],
                    "overlap_exact_rate": field_rates["overlap"],
                    "three_field_mean_rate": diagnostic_mean,
                    "mae": {
                        field: (
                            field_mae_sum[field] / field_mae_count[field]
                            if field_mae_count[field]
                            else None
                        )
                        for field in field_mae_sum
                    },
                    "note": "three_field_mean_rate is diagnostic and never a release gate",
                },
            },
            "identity_all_correct_rate": {
                "numerator": identity_numerator,
                "denominator": identity_denominator,
                "rate": _safe_rate(identity_numerator, identity_denominator),
                "diagnostics": {
                    "same_image_overlap_edges": {
                        "tp": overlap_tp,
                        "fp": overlap_fp,
                        "fn": overlap_fn,
                        "precision": overlap_precision,
                        "recall": overlap_recall,
                        "f1": _f1(overlap_precision, overlap_recall),
                        "false_merge_rate": _safe_rate(overlap_fp, overlap_tp + overlap_fp),
                    },
                    "cross_camera_pairs": {
                        "tp": cross_tp,
                        "fp": cross_fp,
                        "fn": cross_fn,
                        "precision": cross_precision,
                        "recall": cross_recall,
                        "f1": _f1(cross_precision, cross_recall),
                        "false_merge_rate": _safe_rate(cross_fp, cross_tp + cross_fp),
                    },
                },
            },
            "combined_all_correct_rate": {
                "numerator": combined_numerator,
                "denominator": combined_denominator,
                "rate": _safe_rate(combined_numerator, combined_denominator),
                "note": "logical AND of the two primary metrics; not a third independent dimension",
            },
        },
        "decision_coverage": decisions,
        "rows": rows,
        "boundaries": {
            "review_or_abstain_is_not_automatic_success": True,
            "missing_predictions_count_as_failures": True,
            "unique_is_derived": True,
            "localization_iou_is_internal_only": True,
            "area_or_size_accuracy_measured": False,
            "zero_error_claim_is_limited_to_frozen_evaluation_set": True,
        },
    }


def _format_rate(value: float | None) -> str:
    return "未测" if value is None else f"{value * 100:.2f}%"


def render_markdown(report: dict[str, Any]) -> str:
    primary = report["primary_metrics"]
    quantity = primary["quantity_all_correct_rate"]
    identity = primary["identity_all_correct_rate"]
    combined = primary["combined_all_correct_rate"]
    quantity_diagnostics = quantity["diagnostics"]
    identity_diagnostics = identity["diagnostics"]
    lines = [
        "# TruckFlow v3 评测报告",
        "",
        f"- dataset: `{report['dataset_id']}`",
        f"- split: `{report['split']}`",
        f"- protocol: `{report['protocol_version']}`",
        "",
        "## 主指标",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        f"| 数量全对率 | {quantity['numerator']}/{quantity['denominator']} = {_format_rate(quantity['rate'])} |",
        f"| 重叠车辆身份全对率 | {identity['numerator']}/{identity['denominator']} = {_format_rate(identity['rate'])} |",
        f"| 整时刻全对率 | {combined['numerator']}/{combined['denominator']} = {_format_rate(combined['rate'])} |",
        "",
        "## 数量诊断",
        "",
        "| 南机位 | 北机位 | 重合 | 三项平均（仅诊断） |",
        "| ---: | ---: | ---: | ---: |",
        f"| {_format_rate(quantity_diagnostics['south_exact_rate'])} | "
        f"{_format_rate(quantity_diagnostics['north_exact_rate'])} | "
        f"{_format_rate(quantity_diagnostics['overlap_exact_rate'])} | "
        f"{_format_rate(quantity_diagnostics['three_field_mean_rate'])} |",
        "",
        "## 身份诊断",
        "",
    ]
    for label, key in (
        ("同画面重叠边", "same_image_overlap_edges"),
        ("南北同车 pair", "cross_camera_pairs"),
    ):
        metric = identity_diagnostics[key]
        lines.append(
            f"- {label}: P={_format_rate(metric['precision'])}, "
            f"R={_format_rate(metric['recall'])}, F1={_format_rate(metric['f1'])}, "
            f"错误合并率={_format_rate(metric['false_merge_rate'])}"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 人工复核、拒答或无效输出不计自动成功。",
            "- 唯一数由北 + 南 − 重合推导，不单独作为业务指标。",
            "- 定位只用于内部一对一关联，不计算 AP/HOTA。",
            "- 没有可信面积真值，本报告不包含面积准确率。",
            "- 100% 仅在完整标注的冻结评测集内成立。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args()

    report = evaluate(read_json(args.gold), read_json(args.predictions))
    write_json(args.out, report)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(render_markdown(report), encoding="utf-8")
    primary = report["primary_metrics"]
    print(
        "quantity="
        f"{primary['quantity_all_correct_rate']['numerator']}/"
        f"{primary['quantity_all_correct_rate']['denominator']} "
        "identity="
        f"{primary['identity_all_correct_rate']['numerator']}/"
        f"{primary['identity_all_correct_rate']['denominator']}"
    )
    print(args.out)


if __name__ == "__main__":
    main()

