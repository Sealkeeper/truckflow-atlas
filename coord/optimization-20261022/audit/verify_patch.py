"""Prove the suggested patch in memory without modifying evaluator.py.

The frozen evaluator is imported read-only, its quantity structural checker is
replaced by the proposed function below, and the complete audit corpus is run
again.  Output: patch-preview-results.json.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import cases


HERE = Path(__file__).resolve().parent
EVALUATOR_PATH = HERE.parents[1] / "evaluation-v3" / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("truckflow_evaluator", EVALUATOR_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def _patched_prediction_structure(prediction: Any) -> dict[str, Any]:
    problems: list[str] = []
    cameras = prediction.get("cameras") if isinstance(prediction, dict) else None
    quantities = (
        prediction.get("quantities") if isinstance(prediction, dict) else None
    )
    for camera in evaluator.CAMERAS:
        value = cameras.get(camera) if isinstance(cameras, dict) else None
        if not isinstance(value, dict):
            problems.append(f"{camera}_missing_camera")
            continue
        if value.get("status") != "ok":
            problems.append(f"{camera}_status_{value.get('status')}")
        vehicles = value.get("vehicles")
        if not isinstance(vehicles, list):
            problems.append(f"{camera}_vehicles_not_array")
            continue
        count = value.get("count")
        if not evaluator.is_int(count):
            problems.append(f"{camera}_count_missing")
        moment_count = (
            quantities.get(camera) if isinstance(quantities, dict) else None
        )
        if (
            evaluator.is_int(count)
            and evaluator.is_int(moment_count)
            and count != moment_count
        ):
            problems.append(f"{camera}_camera_count_quantity_mismatch")
        if value.get("objects_complete") is not True:
            continue
        ids = [
            vehicle.get("id") if isinstance(vehicle, dict) else None
            for vehicle in vehicles
        ]
        if any(
            not isinstance(identifier, str) or not identifier
            for identifier in ids
        ):
            problems.append(f"{camera}_invalid_vehicle_id")
        elif len(set(ids)) != len(ids):
            problems.append(f"{camera}_duplicate_vehicle_id")
        if evaluator.is_int(count) and count != len(vehicles):
            problems.append(f"{camera}_count_list_mismatch")
    return {"valid": not problems, "problems": problems}


def main() -> None:
    evaluator._prediction_structure = _patched_prediction_structure
    results = []
    for case in cases.build_cases():
        try:
            outcome: dict[str, Any] | BaseException = evaluator.evaluate(
                copy.deepcopy(case.gold), copy.deepcopy(case.predictions)
            )
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            outcome = error
        results.append(
            {
                "case_id": case.case_id,
                "verdict": "PASS" if case.check(outcome) else "FAIL",
                "quantity": (
                    outcome["primary_metrics"]["quantity_all_correct_rate"]
                    if isinstance(outcome, dict)
                    else None
                ),
                "identity": (
                    outcome["primary_metrics"]["identity_all_correct_rate"]
                    if isinstance(outcome, dict)
                    else None
                ),
                "exception": (
                    f"{type(outcome).__name__}: {outcome}"
                    if isinstance(outcome, BaseException)
                    else None
                ),
            }
        )
    failures = [result for result in results if result["verdict"] == "FAIL"]
    (HERE / "patch-preview-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"patched preview: {len(results) - len(failures)}/{len(results)} PASS, "
        f"{len(failures)} FAIL"
    )
    for failure in failures:
        print(failure["case_id"], failure)


if __name__ == "__main__":
    main()
