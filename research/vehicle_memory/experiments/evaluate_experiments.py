"""Evaluate frozen experiment responses against the user count truth.

This script runs only after all model calls have completed. It never feeds the
truth, red-box annotations, or answers back into a model.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


VM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VM_ROOT.parents[1]
EVIDENCE = VM_ROOT / "evidence"
GENERATED = VM_ROOT / "generated"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_truth() -> dict[str, int]:
    payload = read_json(
        REPO_ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
    )
    result: dict[str, int] = {}
    for sample in payload["samples"]:
        time_s = int(sample["time"])
        for camera in ("north", "south"):
            result[f"{camera}_{time_s}"] = int(sample["camera_counts"][camera])
    return result


def load_baseline() -> dict[str, int]:
    metrics = read_json(GENERATED / "metrics.json")
    return {
        row["sample_id"]: int(row["predicted"])
        for row in metrics["per_camera_baseline"]["rows"]
    }


def evaluate_counts(experiment_id: str, truth: dict[str, int]) -> dict[str, Any]:
    manifest = read_json(EVIDENCE / experiment_id / "manifest.json")
    rows: list[dict[str, Any]] = []
    for sample in manifest["ordered_samples"]:
        run = read_json(EVIDENCE / experiment_id / f"{sample}.json")
        gold = truth[sample]
        counts = ((run.get("parsed") or {}).get("counts") or {}) if run.get("ok") else {}
        vehicles = ((run.get("parsed") or {}).get("vehicles") or []) if run.get("ok") else []
        declared = counts.get("total")
        predicted = int(declared) if isinstance(declared, int) and not isinstance(declared, bool) else None
        component_complete = all(
            isinstance(item.get("tractor"), dict)
            and isinstance(item.get("cargo"), dict)
            and bool(item.get("assembly_status"))
            and bool(item.get("assembly_evidence"))
            for item in vehicles
        ) if vehicles else False
        rows.append(
            {
                "sample_id": sample,
                "ok": bool(run.get("ok")),
                "gold": gold,
                "predicted_declared": predicted,
                "predicted_vehicle_rows": len(vehicles),
                "count_fields_consistent": predicted == len(vehicles),
                "error": predicted - gold if predicted is not None else None,
                "exact": predicted == gold,
                "latency_s": run.get("latency_s"),
                "total_tokens": int((run.get("usage") or {}).get("total_tokens") or 0),
                "uncertain_vehicles": sum(bool(item.get("uncertain")) for item in vehicles),
                "assembly_statuses": sorted(
                    {
                        str(item.get("assembly_status"))
                        for item in vehicles
                        if item.get("assembly_status")
                    }
                ),
                "has_component_evidence": component_complete,
            }
        )

    valid = [row for row in rows if row["ok"] and row["predicted_declared"] is not None]
    exact = sum(row["exact"] for row in valid)
    return {
        "experiment_id": experiment_id,
        "manifest": manifest,
        "N": len(rows),
        "valid_N": len(valid),
        "failed_N": len(rows) - len(valid),
        "exact": exact,
        "exact_rate_fixed_denominator": round(exact / max(1, len(rows)), 4),
        "valid_rate": round(len(valid) / max(1, len(rows)), 4),
        "mae": round(statistics.mean(abs(row["error"]) for row in valid), 4)
        if valid
        else None,
        "under_count": sum(row["error"] < 0 for row in valid),
        "over_count": sum(row["error"] > 0 for row in valid),
        "count_field_mismatches": sum(not row["count_fields_consistent"] for row in valid),
        "uncertain_vehicle_rows": sum(row["uncertain_vehicles"] for row in valid),
        "vehicle_rows": sum(row["predicted_vehicle_rows"] for row in valid),
        "component_evidence_complete_runs": sum(row["has_component_evidence"] for row in valid),
        "component_evidence_complete_vehicles": sum(
            row["predicted_vehicle_rows"] for row in valid if row["has_component_evidence"]
        ),
        "rows": rows,
    }


def compare_baseline(summary: dict[str, Any], baseline: dict[str, int]) -> dict[str, Any]:
    rows = []
    for row in summary["rows"]:
        base = baseline[row["sample_id"]]
        predicted = row["predicted_declared"]
        rows.append(
            {
                "sample_id": row["sample_id"],
                "gold": row["gold"],
                "baseline": base,
                "experiment": predicted,
                "baseline_exact": base == row["gold"],
                "experiment_exact": row["exact"],
                "experiment_valid": predicted is not None,
                "delta_prediction": predicted - base if predicted is not None else None,
                "fixed": predicted == row["gold"] and base != row["gold"],
                "regressed": predicted is not None and predicted != row["gold"] and base == row["gold"],
            }
        )
    return {
        "N": len(rows),
        "baseline_exact": sum(row["baseline_exact"] for row in rows),
        "experiment_exact": sum(row["experiment_exact"] for row in rows),
        "failed": sum(not row["experiment_valid"] for row in rows),
        "fixed": sum(row["fixed"] for row in rows),
        "regressed": sum(row["regressed"] for row in rows),
        "unchanged": sum(
            row["experiment"] == row["baseline"]
            for row in rows
            if row["experiment"] is not None
        ),
        "rows": rows,
    }


def main() -> None:
    truth = load_truth()
    baseline = load_baseline()
    dual = evaluate_counts("dualscale_v1", truth)
    component = evaluate_counts("component_assembly_v1", truth)
    dual["baseline_comparison"] = compare_baseline(dual, baseline)
    component["baseline_comparison"] = compare_baseline(component, baseline)
    result = {
        "schema": "truckflow-vehicle-memory-experiments-v1",
        "truth_source": "accuracy/reviewed/user-final-review-v2-2026-10-21.json",
        "evaluation_policy": (
            "truth and user annotations used only after frozen model calls; "
            "count fields use a fixed valid denominator"
        ),
        "id_metrics": {
            "status": "untested",
            "reason": "no complete human cargo_id, tractor_id, or vehicle_session_id truth",
        },
        "dualscale_v1": dual,
        "component_assembly_v1": component,
    }
    write_json(GENERATED / "experiment_metrics.json", result)
    for key in ("dualscale_v1", "component_assembly_v1"):
        block = result[key]
        print(
            json.dumps(
                {
                    "experiment": key,
                    "N": block["N"],
                    "valid_N": block["valid_N"],
                    "failed_N": block["failed_N"],
                    "exact": block["exact"],
                    "mae": block["mae"],
                    "under": block["under_count"],
                    "over": block["over_count"],
                    "baseline_comparison": {
                        "fixed": block["baseline_comparison"]["fixed"],
                        "regressed": block["baseline_comparison"]["regressed"],
                        "unchanged": block["baseline_comparison"]["unchanged"],
                    },
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
