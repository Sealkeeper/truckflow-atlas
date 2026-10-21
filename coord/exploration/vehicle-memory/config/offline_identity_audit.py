"""Audit whether the archived data can support an offline identity experiment.

This script makes no network or model calls. It separates structural policy
checks from identity accuracy and fails closed when human identity truth is
missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


IDENTITY_KEYS = {"cargo_id", "tractor_id", "vehicle_session_id"}


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "accuracy" / "reviewed").is_dir():
            return candidate
    raise RuntimeError("could not locate repository root")


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = find_repo_root(SCRIPT_DIR)
VM_ROOT = (
    SCRIPT_DIR
    if (SCRIPT_DIR / "generated").is_dir()
    else REPO_ROOT / "research" / "vehicle_memory"
)
GENERATED = VM_ROOT / "generated"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(collect_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(collect_keys(child))
    return keys


def main() -> None:
    passports_payload = read_json(GENERATED / "passports.json")
    passports = passports_payload["passports"]
    memory_cache = read_json(GENERATED / "memory_cache.json")
    metrics = read_json(GENERATED / "metrics.json")
    pair_cases = read_json(GENERATED / "memory_pair_cases.json")
    truth = read_json(
        REPO_ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
    )
    attachments = read_json(
        REPO_ROOT / "review" / "user-attachments-20261021" / "manifest.json"
    )

    human_identity_keys = sorted(collect_keys(truth) & IDENTITY_KEYS)
    memory_metadata_fields = {
        "source",
        "observed_at_video_s",
        "created_at_utc",
        "version",
        "ttl_s",
        "expires_at_utc",
        "state",
        "conflicts",
        "supersedes",
    }
    cache_entries = memory_cache["entries"]
    pair_rows = pair_cases["rows"]

    checks = {
        "passport_count_66": len(passports) == 66,
        "all_identity_layers_present": all(
            set(passport["identity_layers"]) == IDENTITY_KEYS for passport in passports
        ),
        "cargo_id_values_unverified": all(
            passport["identity_layers"]["cargo_id"]["value"] is None
            for passport in passports
        ),
        "tractor_id_values_unverified": all(
            passport["identity_layers"]["tractor_id"]["value"] is None
            for passport in passports
        ),
        "raw_text_not_promoted_to_cargo_or_tractor": all(
            not passport["identity_layers"]["cargo_id"]["candidate_tokens"]
            and not passport["identity_layers"]["tractor_id"]["candidate_tokens"]
            for passport in passports
        ),
        "session_ids_unique_per_observation": len(
            {p["identity_layers"]["vehicle_session_id"]["value"] for p in passports}
        )
        == len(passports),
        "confirmed_identity_count_zero": sum(
            passport["status"] == "confirmed" for passport in passports
        )
        == 0,
        "all_passports_have_memory_metadata": all(
            memory_metadata_fields <= set(passport["memory_metadata"])
            for passport in passports
        ),
        "all_cache_entries_have_memory_metadata": all(
            memory_metadata_fields <= set(entry) for entry in cache_entries
        ),
        "cross_camera_auto_release_zero": metrics["cross_camera"][
            "auto_released_frames"
        ]
        == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise AssertionError(f"identity policy audit failed: {failed_checks}")

    audit = {
        "schema": "truckflow-offline-identity-audit-v1",
        "scope": "zero-model-call data and policy audit",
        "model_calls": 0,
        "data_inventory": {
            "times": metrics["dataset"]["times"],
            "camera_frames": metrics["dataset"]["samples"],
            "provisional_passports": len(passports),
            "confirmed_passports": sum(p["status"] == "confirmed" for p in passports),
            "typed_cargo_id_values": sum(
                p["identity_layers"]["cargo_id"]["value"] is not None for p in passports
            ),
            "typed_tractor_id_values": sum(
                p["identity_layers"]["tractor_id"]["value"] is not None
                for p in passports
            ),
            "provisional_session_ids": len(
                {p["identity_layers"]["vehicle_session_id"]["value"] for p in passports}
            ),
            "human_identity_truth_fields": human_identity_keys,
            "human_trailer_swap_events": 0,
            "prior_only_future_split_records": 0,
            "user_red_box_images": len(attachments["records"]),
            "user_red_box_review_times": len(
                {record["time"] for record in attachments["records"]}
            ),
            "cross_camera_pair_cases": len(pair_rows),
            "cross_camera_pair_positive_labels": sum(
                row["gold"] == "yes" for row in pair_rows
            ),
            "cross_camera_pair_negative_labels": sum(
                row["gold"] == "no" for row in pair_rows
            ),
            "memory_entries": len(cache_entries),
        },
        "policy_checks": checks,
        "measured_related_metrics": {
            "count_baseline": {
                "exact": metrics["per_camera_baseline"]["exact"],
                "N": metrics["per_camera_baseline"]["n"],
                "mae": metrics["per_camera_baseline"]["mae"],
            },
            "cross_camera_auto_release": {
                "auto_released_frames": metrics["cross_camera"][
                    "auto_released_frames"
                ],
                "review_frames": metrics["cross_camera"]["review_frames"],
            },
            "semantic_pair_cases": {
                "exact": pair_cases["metrics"]["exact"],
                "N": pair_cases["metrics"]["cases"],
                "auto_yes": pair_cases["metrics"]["tp"],
                "review": pair_cases["metrics"]["review_count"],
            },
        },
        "identity_metrics": {
            "status": "untested",
            "reason": (
                "Archived review provides counts, overlap counts, and sparse same-vehicle "
                "pair labels, but no complete human cargo_id, tractor_id, "
                "vehicle_session_id, or trailer-swap truth."
            ),
        },
        "offline_experiment_gate": {
            "ready": False,
            "blocking_evidence": [
                "no human cargo_id / tractor_id / vehicle_session_id labels",
                "no human-labelled trailer swap events",
                "no independent prior-only history and future target split",
                "pair labels cover only 8 candidate pairs and do not identify typed IDs",
            ],
        },
    }
    output = GENERATED / "offline_identity_audit.json"
    output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
