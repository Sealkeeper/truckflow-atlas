from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    EvaluationError,
    audit_roof_only_sample,
    evaluate_camera_counts,
    evaluate_times,
    load_canonical_output,
    normalize_bbox,
    summarize_cost,
    truth_map,
)


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def vehicle(
    instance_id: str,
    bbox: list[float] | None = None,
    *,
    bbox_space: str | None = None,
) -> dict:
    row = {
        "id": instance_id,
        "bbox": bbox or [0.10, 0.10, 0.30, 0.30],
    }
    if bbox_space is not None:
        row["bbox_space"] = bbox_space
    return row


def sample(
    sample_id: str,
    camera: str,
    time_s: int,
    vehicles: list[dict],
    *,
    predicted_count: int | None = None,
    bbox_space: str = "aisle_norm_0_1",
    **extra,
) -> dict:
    return {
        "sample_id": sample_id,
        "camera": camera,
        "time": time_s,
        "status": "valid",
        "predicted_count": (
            len(vehicles) if predicted_count is None else predicted_count
        ),
        "vehicles": vehicles,
        "bbox_space": bbox_space,
        **extra,
    }


def canonical(samples: list[dict], times: list[dict] | None = None) -> dict:
    return {
        "schema": "round2-canonical-output-v1",
        "samples": samples,
        "times": times or [],
    }


def load(tmp_path: Path, doc: dict) -> dict:
    return load_canonical_output(write_json(tmp_path / "output.json", doc))


def roof_observation(observation_id: str = "R1") -> dict:
    return {
        "id": observation_id,
        "bbox_space": "aisle_norm_0_1",
        "roof_bbox": [0.10, 0.15, 0.40, 0.35],
        "top_state": "top_open",
        "evidence_tags": ["roof", "top_edge"],
        "component": "unknown",
    }


def roof_entity(
    entity_id: str = "P1",
    *,
    refs: list[str] | None = None,
    component: str = "unknown",
) -> dict:
    return {
        "id": entity_id,
        "component": component,
        "observation_ids": refs or ["R1"],
        "identity_status": "unknown",
    }


def roof_sample(
    *,
    observations: list[dict] | None = None,
    entities: list[dict] | None = None,
    release: str = "review",
) -> dict:
    observations = (
        [roof_observation()] if observations is None else observations
    )
    entities = [roof_entity()] if entities is None else entities
    return {
        "sample_id": "north_5",
        "camera": "north",
        "time": 5,
        "evidence_scope": "roof_only",
        "predicted_count": len(entities),
        "physical_entities": entities,
        "roof_observations": observations,
        "release_decision": release,
    }


def test_roof_top_open_with_two_observations_for_one_physical_entity_is_valid():
    observation_2 = roof_observation("R2")
    observation_2["roof_bbox"] = [0.41, 0.15, 0.65, 0.36]
    doc = roof_sample(
        observations=[roof_observation("R1"), observation_2],
        entities=[roof_entity(refs=["R1", "R2"])],
    )
    audit = audit_roof_only_sample(doc)
    assert audit["pass"] is True
    assert audit["observation_count"] == 2
    assert audit["physical_entity_count"] == 1
    assert audit["merged_observation_count"] == 2


def test_uncertain_group_assigns_roof_without_increasing_physical_count(tmp_path):
    doc = roof_sample(
        observations=[roof_observation("R1"), roof_observation("R2")],
        entities=[roof_entity(refs=["R1"])],
    )
    doc["uncertain"] = [
        {"roof_ids": ["R2"], "reason": "top boundary does not confirm a vehicle"}
    ]
    audit = audit_roof_only_sample(doc)
    assert audit["pass"] is True
    assert audit["physical_entity_count"] == 1
    assert audit["uncertain_group_count"] == 1
    assert audit["uncertain_observation_count"] == 1

    output = load(
        tmp_path,
        canonical([{**doc, "vehicles": doc["physical_entities"]}]),
    )
    assert output["samples"]["north_5"]["status"] == "valid"


def test_zero_confirmed_vehicles_with_uncertain_roof_is_valid(tmp_path):
    doc = roof_sample(
        observations=[roof_observation("R1")],
        entities=[],
        release="review",
    )
    doc["uncertain"] = [
        {"roof_ids": ["R1"], "reason": "roof boundary is ambiguous"}
    ]
    output = load(tmp_path, canonical([doc]))
    parsed = output["samples"]["north_5"]
    assert parsed["status"] == "valid"
    assert parsed["predicted_count"] == 0
    assert parsed["roof_only_audit"]["uncertain_group_count"] == 1


def test_auto_release_with_uncertain_group_is_contract_failure():
    doc = roof_sample(
        observations=[roof_observation("R1"), roof_observation("R2")],
        entities=[roof_entity(refs=["R1"])],
        release="auto_release",
    )
    doc["uncertain"] = [{"roof_ids": ["R2"], "reason": "unknown grouping"}]
    audit = audit_roof_only_sample(doc)
    assert audit["pass"] is False
    assert "auto-release despite uncertain roof groups" in audit["issues"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda doc: doc.update(
                roof_observations=[
                    roof_observation("R1"),
                    roof_observation("R2"),
                ]
            ),
            "not assigned to a physical entity",
        ),
        (
            lambda doc: doc.update(
                physical_entities=[
                    roof_entity("P1", refs=["R1"]),
                    roof_entity("P2", refs=["R1"]),
                ],
                predicted_count=2,
            ),
            "assigned to multiple physical entities",
        ),
        (
            lambda doc: doc["roof_observations"][0].update(
                evidence_tags=["plate"]
            ),
            "non-roof evidence tags",
        ),
        (
            lambda doc: doc.update(
                physical_entities=[
                    roof_entity(component="cab_roof"),
                ]
            ),
            "without grouping_basis",
        ),
        (
            lambda doc: (
                doc["roof_observations"][0].update(top_state="unknown"),
                doc.update(release_decision="auto_release"),
            ),
            "auto-release despite unknown",
        ),
    ],
)
def test_roof_only_contract_rejects_invalid_evidence(change, message):
    doc = roof_sample()
    change(doc)
    audit = audit_roof_only_sample(doc)
    assert audit["pass"] is False
    assert any(message in issue for issue in audit["issues"])


def test_duplicate_sample_id_raises(tmp_path):
    doc = canonical(
        [
            sample("same", "north", 5, [vehicle("N1")]),
            sample("same", "south", 5, [vehicle("S1")]),
        ]
    )
    with pytest.raises(EvaluationError, match="duplicate sample_id"):
        load(tmp_path, doc)


def test_duplicate_camera_time_raises(tmp_path):
    doc = canonical(
        [
            sample("north_5_a", "north", 5, [vehicle("N1")]),
            sample("north_5_b", "north", 5, [vehicle("N2")]),
        ]
    )
    with pytest.raises(EvaluationError, match="duplicate time/camera"):
        load(tmp_path, doc)


def test_duplicate_instance_id_fails_sample_without_overwrite(tmp_path):
    output = load(
        tmp_path,
        canonical(
            [
                sample(
                    "north_5",
                    "north",
                    5,
                    [
                        vehicle("DUP", [0.10, 0.10, 0.20, 0.20]),
                        vehicle("DUP", [0.30, 0.10, 0.40, 0.20]),
                    ],
                )
            ]
        ),
    )
    parsed = output["samples"]["north_5"]
    assert parsed["status"] == "failed"
    assert parsed["ids"] == ["DUP", "DUP"]
    assert any("duplicate instance IDs" in issue for issue in parsed["issues"])


def test_count_list_mismatch_fails_sample(tmp_path):
    output = load(
        tmp_path,
        canonical(
            [
                sample(
                    "north_5",
                    "north",
                    5,
                    [vehicle("N1")],
                    predicted_count=2,
                )
            ]
        ),
    )
    parsed = output["samples"]["north_5"]
    assert parsed["status"] == "failed"
    assert parsed["count_matches_instances"] is False
    assert any("reported count 2" in issue for issue in parsed["issues"])


def test_coordinate_spaces_are_explicit_and_do_not_share_one_scale(tmp_path):
    _, strict_box, strict_error = normalize_bbox(
        [100, 200, 300, 400], "aisle_norm_0_1"
    )
    _, compatible_box, compatible_error = normalize_bbox(
        [100, 200, 300, 400], "aisle_int_0_1000"
    )
    assert strict_box is None
    assert "outside aisle_norm_0_1" in strict_error
    assert compatible_error is None
    assert compatible_box == pytest.approx([0.3140625, 0.2, 0.3953125, 0.4])

    output = load(
        tmp_path,
        canonical(
            [
                sample(
                    "north_5",
                    "north",
                    5,
                    [
                        vehicle("N1", [0.10, 0.10, 0.20, 0.20]),
                        vehicle(
                            "N2",
                            [100, 200, 300, 400],
                            bbox_space="aisle_int_0_1000",
                        ),
                    ],
                    bbox_space="aisle_norm_0_1",
                )
            ]
        ),
    )
    assert output["samples"]["north_5"]["status"] == "valid"


def test_overlap_unique_formula_mismatch_invalidates_time(tmp_path):
    output = load(
        tmp_path,
        canonical(
            [
                sample(
                    "north_5",
                    "north",
                    5,
                    [vehicle("N1"), vehicle("N2", [0.40, 0.10, 0.60, 0.30])],
                ),
                sample(
                    "south_5",
                    "south",
                    5,
                    [vehicle("S1"), vehicle("S2", [0.40, 0.10, 0.60, 0.30])],
                ),
            ],
            [
                {
                    "time": 5,
                    "status": "valid",
                    "overlap": 1,
                    "unique": 5,
                    "matches": [{"north_id": "N1", "south_id": "S1"}],
                    "release_decision": "review",
                }
            ],
        ),
    )
    truth = {
        5: {
            "time": 5,
            "north": 2,
            "south": 2,
            "overlap": 1,
            "unique": 3,
            "formula_unique": 3,
        }
    }
    overlap, unique, issues = evaluate_times(truth, output["samples"], output["times"])
    assert overlap["valid_n"] == 0
    assert overlap["failed"] == 1
    assert unique["valid_n"] == 0
    assert unique["failed"] == 1
    assert issues
    assert any("N+S-overlap" in issue["issues"][0] for issue in issues)


def test_missing_truth_label_is_not_scored_as_zero(tmp_path):
    truth_path = write_json(
        tmp_path / "truth.json",
        {
            "schema": "test-truth",
            "complete": False,
            "samples": [
                {
                    "time": 5,
                    "completed": True,
                    "camera_counts": {"south": 3},
                    "overlap": 1,
                    "unique_total": 4,
                }
            ],
        },
    )
    camera_truth, _, metadata = truth_map(truth_path)
    assert camera_truth["north_5"]["value"] is None
    assert camera_truth["south_5"]["value"] == 3
    assert "north_5" in metadata["incomplete_camera_slots"]

    output = load(
        tmp_path,
        canonical(
            [
                sample("south_5", "south", 5, [vehicle("S1")])
            ]
        ),
    )
    result = evaluate_camera_counts(camera_truth, output["samples"])
    assert result["label_missing"] == 1
    assert result["scored_n"] == 1
    assert result["exact"] == 0
    assert result["missing"] == 1


def test_initialization_and_online_cost_are_added_separately():
    samples = {
        "north_5": {
            "calls": 1,
            "images": 2,
            "tokens": 100,
            "latency_s": 10.0,
        },
        "south_5": {
            "calls": 1,
            "images": 2,
            "tokens": 150,
            "latency_s": 20.0,
        },
    }
    cost = summarize_cost(
        samples,
        {
            "online": {"calls": 2, "images": 4, "tokens": 250},
            "initialization": {
                "calls": 3,
                "images": 5,
                "tokens": 700,
                "latency_s": 40.0,
            },
            "concurrency": 2,
        },
    )
    assert cost["online_observed"]["calls"] == 2
    assert cost["online_observed"]["images"] == 4
    assert cost["online_observed"]["tokens"] == 250
    assert cost["combined_online_plus_initialization"] == {
        "calls": 5,
        "images": 9,
        "tokens": 950,
        "latency_s_total": 70.0,
    }
