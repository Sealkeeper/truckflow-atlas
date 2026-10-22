from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("truckflow_evaluator", MODULE_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def vehicle(identifier: str, x: float) -> dict:
    return {
        "id": identifier,
        "bbox": [x, 0.1, 0.2, 0.2],
        "occlusion": "none",
        "truncation": "none",
    }


def camera(prefix: str, count: int) -> dict:
    return {
        "image": f"{prefix}.png",
        "sha256": "0" * 64,
        "width": 1000,
        "height": 1000,
        "eligible": True,
        "vehicles": [vehicle(f"{prefix}{index}", 0.05 + index * 0.25) for index in range(1, count + 1)],
    }


def gold_document() -> dict:
    return {
        "schema": "truckflow-gold-v3",
        "dataset_id": "test-set",
        "split": "blind",
        "moments": [
            {
                "moment_id": "m1",
                "time_s": 10,
                "cameras": {"south": camera("s", 2), "north": camera("n", 2)},
                "overlap_edges": [["s1", "s2"]],
                "cross_camera_pairs": [["s1", "n1"]],
                "quantities": {"south": 2, "north": 2, "overlap": 1, "unique": 3},
                "truth_complete": {"quantity": True, "identity": True},
            },
            {
                "moment_id": "m2",
                "time_s": 20,
                "cameras": {"south": camera("s", 1), "north": camera("n", 1)},
                "overlap_edges": [],
                "cross_camera_pairs": [],
                "quantities": {"south": 1, "north": 1, "overlap": 0, "unique": 2},
                "truth_complete": {"quantity": True, "identity": True},
            },
        ],
    }


def predictions_document() -> dict:
    return {
        "schema": "truckflow-predictions-v3",
        "dataset_id": "test-set",
        "moments": [
            {
                "moment_id": "m1",
                "decision": "auto",
                "cameras": {
                    "south": {"status": "ok", "count": 2, "objects_complete": True, "vehicles": [vehicle("ps1", 0.3), vehicle("ps2", 0.55)]},
                    "north": {"status": "ok", "count": 2, "objects_complete": True, "vehicles": [vehicle("pn1", 0.3), vehicle("pn2", 0.55)]},
                },
                "overlap_edges": [["ps1", "ps2"]],
                "cross_camera_pairs": [["ps1", "pn1"]],
                "quantities": {"south": 2, "north": 2, "overlap": 1, "unique": 3},
            },
            {
                "moment_id": "m2",
                "decision": "auto",
                "cameras": {
                    "south": {"status": "ok", "count": 1, "objects_complete": True, "vehicles": [vehicle("ps3", 0.3)]},
                    "north": {"status": "ok", "count": 1, "objects_complete": True, "vehicles": [vehicle("pn3", 0.3)]},
                },
                "overlap_edges": [],
                "cross_camera_pairs": [],
                "quantities": {"south": 1, "north": 1, "overlap": 0, "unique": 2},
            },
        ],
    }


def test_perfect_report_is_two_hundred_percent_primary() -> None:
    report = evaluator.evaluate(gold_document(), predictions_document())
    metrics = report["primary_metrics"]
    assert metrics["quantity_all_correct_rate"]["rate"] == 1.0
    assert metrics["identity_all_correct_rate"]["rate"] == 1.0
    assert metrics["combined_all_correct_rate"]["rate"] == 1.0


def test_quantity_one_field_wrong_fails_moment_and_keeps_fixed_denominator() -> None:
    prediction = predictions_document()
    prediction["moments"][1]["quantities"]["south"] = 2
    prediction["moments"][1]["quantities"]["unique"] = 3
    report = evaluator.evaluate(gold_document(), prediction)
    quantity = report["primary_metrics"]["quantity_all_correct_rate"]
    assert quantity["numerator"] == 1
    assert quantity["denominator"] == 2
    assert quantity["diagnostics"]["south_exact_rate"] == 0.5


def test_unique_formula_mismatch_invalidates_count() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["quantities"]["unique"] = 4
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["quantity_all_correct_rate"]["numerator"] == 1
    assert report["rows"][0]["quantity"]["formula_valid"] is False


def test_overlap_count_wrong_fails_quantity() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["quantities"]["overlap"] = 0
    prediction["moments"][0]["quantities"]["unique"] = 4
    report = evaluator.evaluate(gold_document(), prediction)
    quantity = report["primary_metrics"]["quantity_all_correct_rate"]
    assert quantity["numerator"] == 1


def test_wrong_cross_pair_with_same_count_fails_identity() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cross_camera_pairs"] = [["ps2", "pn1"]]
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["quantity_all_correct_rate"]["rate"] == 1.0
    assert report["primary_metrics"]["identity_all_correct_rate"]["numerator"] == 1


def test_merged_overlap_objects_fail_identity_even_if_count_claims_two() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cameras"]["south"]["vehicles"] = [vehicle("ps1", 0.3)]
    prediction["moments"][0]["cameras"]["south"]["objects_complete"] = False
    prediction["moments"][0]["overlap_edges"] = []
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["quantity_all_correct_rate"]["rate"] == 1.0
    assert report["primary_metrics"]["identity_all_correct_rate"]["numerator"] == 1
    assert "south_mapping_incomplete" in report["rows"][0]["reasons"]


def test_missing_overlap_edge_fails_identity() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["overlap_edges"] = []
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["identity_all_correct_rate"]["numerator"] == 1
    assert report["primary_metrics"]["identity_all_correct_rate"]["diagnostics"]["same_image_overlap_edges"]["fn"] == 1


def test_duplicate_cross_pair_is_invalid_identity() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cross_camera_pairs"] = [["ps1", "pn1"], ["ps1", "pn1"]]
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["identity_all_correct_rate"]["numerator"] == 1
    assert any("cross_pair_structure_invalid" in reason for reason in report["rows"][0]["reasons"])


def test_review_decision_is_not_automatic_success() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["decision"] = "review"
    report = evaluator.evaluate(gold_document(), prediction)
    row = report["rows"][0]
    assert row["quantity"]["raw_all_correct"] is True
    assert row["quantity"]["all_correct"] is False
    assert row["identity"]["raw_all_correct"] is True
    assert row["identity"]["all_correct"] is False
    assert report["decision_coverage"]["review"] == 1


def test_incomplete_quantity_truth_only_excludes_quantity_denominator() -> None:
    gold = gold_document()
    gold["moments"][1]["truth_complete"]["quantity"] = False
    report = evaluator.evaluate(gold, predictions_document())
    assert report["primary_metrics"]["quantity_all_correct_rate"]["denominator"] == 1
    assert report["primary_metrics"]["identity_all_correct_rate"]["denominator"] == 2
    assert report["primary_metrics"]["combined_all_correct_rate"]["denominator"] == 1


def test_missing_prediction_counts_as_failure() -> None:
    prediction = predictions_document()
    prediction["moments"] = prediction["moments"][:1]
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["primary_metrics"]["quantity_all_correct_rate"]["denominator"] == 2
    assert report["primary_metrics"]["quantity_all_correct_rate"]["numerator"] == 1
    assert report["decision_coverage"]["missing"] == 1


def test_iou_matching_is_one_to_one_and_deterministic() -> None:
    gold = [vehicle("g1", 0.1), vehicle("g2", 0.12)]
    predicted = [vehicle("p1", 0.11)]
    first = evaluator.one_to_one_vehicle_match(gold, predicted)
    second = evaluator.one_to_one_vehicle_match(copy.deepcopy(gold), copy.deepcopy(predicted))
    assert first["tp"] == 1
    assert first["fp"] == 0
    assert first["fn"] == 1
    assert first["gold_to_pred"] == second["gold_to_pred"]
    assert first["gold_to_pred"] == {"g1": "p1"}


def test_invalid_gold_unique_formula_is_rejected() -> None:
    gold = gold_document()
    gold["moments"][0]["quantities"]["unique"] = 4
    with pytest.raises(evaluator.EvalError):
        evaluator.evaluate(gold, predictions_document())


def test_duplicate_prediction_moment_is_rejected() -> None:
    prediction = predictions_document()
    prediction["moments"].append(copy.deepcopy(prediction["moments"][0]))
    with pytest.raises(evaluator.EvalError):
        evaluator.evaluate(gold_document(), prediction)


def test_dataset_mismatch_is_rejected() -> None:
    prediction = predictions_document()
    prediction["dataset_id"] = "other"
    with pytest.raises(evaluator.EvalError):
        evaluator.evaluate(gold_document(), prediction)


# --- 3.0.1 red-team regressions -------------------------------------------


def test_camera_abstain_cannot_win_quantity() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cameras"]["south"]["status"] = "abstain"
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["rows"][0]["quantity"]["all_correct"] is False
    assert any(
        "south_status_abstain" in problem
        for problem in report["rows"][0]["quantity"]["structure"]["problems"]
    )


def test_duplicate_ids_cannot_win_quantity_when_complete() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cameras"]["south"]["vehicles"][1]["id"] = "ps1"
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["rows"][0]["quantity"]["all_correct"] is False
    assert report["rows"][0]["quantity"]["raw_all_correct"] is False


def test_missing_object_list_does_not_veto_quantity() -> None:
    prediction = predictions_document()
    south = prediction["moments"][0]["cameras"]["south"]
    south["objects_complete"] = False
    south["vehicles"] = [vehicle("ps1", 0.3)]
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["rows"][0]["quantity"]["all_correct"] is True
    assert report["rows"][0]["identity"]["all_correct"] is False


def test_partial_quantity_truth_skips_denominator_without_crashing() -> None:
    gold = gold_document()
    gold["moments"][0]["quantities"] = {
        "south": None,
        "north": None,
        "overlap": None,
        "unique": None,
    }
    gold["moments"][0]["truth_complete"]["quantity"] = False
    report = evaluator.evaluate(gold, predictions_document())
    quantity = report["primary_metrics"]["quantity_all_correct_rate"]
    identity = report["primary_metrics"]["identity_all_correct_rate"]
    assert (quantity["numerator"], quantity["denominator"]) == (1, 1)
    assert (identity["numerator"], identity["denominator"]) == (2, 2)


def test_duplicate_gold_time_is_rejected() -> None:
    gold = gold_document()
    gold["moments"][1]["time_s"] = gold["moments"][0]["time_s"]
    with pytest.raises(evaluator.EvalError):
        evaluator.evaluate(gold, predictions_document())


def test_bbox_tiny_out_of_range_is_invalid() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [0.9, 0.1, 0.1000005, 0.2]
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["rows"][0]["identity"]["all_correct"] is False


def test_null_camera_count_cannot_win_either_metric() -> None:
    prediction = predictions_document()
    prediction["moments"][0]["cameras"]["south"]["count"] = None
    report = evaluator.evaluate(gold_document(), prediction)
    row = report["rows"][0]
    assert row["quantity"]["all_correct"] is False
    assert row["identity"]["all_correct"] is False


def test_camera_count_disagreeing_with_quantities_fails() -> None:
    prediction = predictions_document()
    south = prediction["moments"][0]["cameras"]["south"]
    south["count"] = 0
    south["vehicles"] = []
    south["objects_complete"] = False
    report = evaluator.evaluate(gold_document(), prediction)
    assert report["rows"][0]["quantity"]["all_correct"] is False
    assert any(
        "count_disagrees_with_quantities" in problem
        for problem in report["rows"][0]["quantity"]["structure"]["problems"]
    )

