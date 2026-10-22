"""Security regression tests for the frozen TruckFlow v3 evaluator.

Confirmed vulnerabilities are marked ``xfail(strict=True)`` so the suite stays
runnable while preserving the expected secure behavior.  Once the evaluator
is patched, those cases become XPASS and strict mode turns the suite red until
the markers are removed.
"""

from __future__ import annotations

import copy
import importlib.util
import itertools
from pathlib import Path

import pytest

import cases


HERE = Path(__file__).resolve().parent
COORD_ROOT = HERE.parents[1]
EVALUATOR_PATH = COORD_ROOT / "evaluation-v3" / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("truckflow_evaluator", EVALUATOR_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


CONFIRMED_FAILURES = {
    "A14d-camera-count-null",
    "A14e-camera-contradiction",
}


@pytest.mark.parametrize(
    "case", cases.build_cases(), ids=lambda case: case.case_id
)
def test_redteam_case(case: cases.Case, request: pytest.FixtureRequest) -> None:
    if case.case_id in CONFIRMED_FAILURES:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason="confirmed evaluator vulnerability; see REPORT.md",
            )
        )
    try:
        report = evaluator.evaluate(
            copy.deepcopy(case.gold), copy.deepcopy(case.predictions)
        )
        outcome: dict | BaseException = report
    except (evaluator.EvalError, TypeError, ValueError) as error:
        outcome = error
    assert case.check(outcome), (
        f"{case.case_id}: expected secure behavior {case.expected!r}; "
        f"actual={outcome!r}"
    )


def test_perfect_fixture_reaches_both_one() -> None:
    report = evaluator.evaluate(
        cases.gold_document(), cases.prediction_document()
    )
    assert (
        report["primary_metrics"]["quantity_all_correct_rate"]["rate"] == 1.0
    )
    assert (
        report["primary_metrics"]["identity_all_correct_rate"]["rate"] == 1.0
    )
    assert (
        report["primary_metrics"]["combined_all_correct_rate"]["rate"] == 1.0
    )


def test_iou_exactly_half_is_inclusive() -> None:
    iou = evaluator.bbox_iou(
        [0.0, 0.0, 0.2, 0.2],
        [0.05, 0.0, 0.1, 0.2],
    )
    assert iou == 0.5
    match = evaluator.one_to_one_vehicle_match(
        [cases.vehicle("g", 0.0)],
        [cases.vehicle("p", 0.05)],
    )
    assert match["tp"] == 1


def test_matching_is_deterministic_under_list_order_exchange() -> None:
    gold = [cases.vehicle("g1", 0.1), cases.vehicle("g2", 0.1)]
    predictions = [cases.vehicle("p1", 0.1), cases.vehicle("p2", 0.1)]
    mappings = set()
    for gold_order in itertools.permutations(gold):
        for prediction_order in itertools.permutations(predictions):
            match = evaluator.one_to_one_vehicle_match(
                list(gold_order), list(prediction_order)
            )
            mappings.add(tuple(sorted(match["gold_to_pred"].items())))
    assert mappings == {(("g1", "p1"), ("g2", "p2"))}


def test_quantity_and_identity_do_not_pollute_each_other() -> None:
    prediction = cases.prediction_document()
    prediction["moments"][0]["cross_camera_pairs"] = [["ps2", "pn1"]]
    report = evaluator.evaluate(cases.gold_document(), prediction)
    metrics = report["primary_metrics"]
    assert metrics["quantity_all_correct_rate"]["rate"] == 1.0
    assert metrics["identity_all_correct_rate"]["rate"] == 0.0
