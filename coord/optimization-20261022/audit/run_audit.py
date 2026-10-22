"""Run the offline TruckFlow v3 red-team corpus and materialize evidence.

Usage:
    python run_audit.py

Only reads coord/evaluation-v3/ and writes below this audit directory.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
from typing import Any

import cases


HERE = Path(__file__).resolve().parent
COORD_ROOT = HERE.parents[1]
EVALUATOR_PATH = COORD_ROOT / "evaluation-v3" / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("truckflow_evaluator", EVALUATOR_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    primary = report["primary_metrics"]
    return {
        "quantity": {
            key: primary["quantity_all_correct_rate"][key]
            for key in ("numerator", "denominator", "rate")
        },
        "identity": {
            key: primary["identity_all_correct_rate"][key]
            for key in ("numerator", "denominator", "rate")
        },
        "combined": {
            key: primary["combined_all_correct_rate"][key]
            for key in ("numerator", "denominator", "rate")
        },
        "rows": [
            {
                "moment_id": row["moment_id"],
                "decision": row["decision"],
                "quantity_all_correct": row["quantity"]["all_correct"],
                "quantity_raw_all_correct": row["quantity"]["raw_all_correct"],
                "identity_all_correct": row["identity"]["all_correct"],
                "identity_raw_all_correct": row["identity"]["raw_all_correct"],
                "reasons": row["reasons"],
            }
            for row in report["rows"]
        ],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cases() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases.build_cases():
        try:
            report = evaluator.evaluate(
                copy.deepcopy(case.gold), copy.deepcopy(case.predictions)
            )
            outcome: dict[str, Any] | BaseException = report
            actual: dict[str, Any] = {
                "kind": "report",
                "summary": summarize(report),
            }
        except BaseException as error:  # Audit must record crashes as outcomes.
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            outcome = error
            actual = {
                "kind": "exception",
                "type": type(error).__name__,
                "message": str(error),
            }
        passed = bool(case.check(outcome))
        results.append(
            {
                "case_id": case.case_id,
                "attack": case.attack,
                "expected_secure": case.expected,
                "gold": case.gold,
                "predictions": case.predictions,
                "actual": actual,
                "verdict": "PASS" if passed else "FAIL",
            }
        )
    return results


def run_determinism() -> dict[str, Any]:
    gold = [
        cases.vehicle("g1", 0.1),
        cases.vehicle("g2", 0.1),
    ]
    predictions = [
        cases.vehicle("p1", 0.1),
        cases.vehicle("p2", 0.1),
    ]
    observations: list[dict[str, Any]] = []
    for gold_order in itertools.permutations(gold):
        for prediction_order in itertools.permutations(predictions):
            match = evaluator.one_to_one_vehicle_match(
                list(gold_order), list(prediction_order)
            )
            observations.append(
                {
                    "gold_order": [item["id"] for item in gold_order],
                    "prediction_order": [
                        item["id"] for item in prediction_order
                    ],
                    "gold_to_pred": match["gold_to_pred"],
                    "tp": match["tp"],
                    "fp": match["fp"],
                    "fn": match["fn"],
                }
            )
    mappings = {
        json.dumps(item["gold_to_pred"], sort_keys=True)
        for item in observations
    }
    return {
        "attack": "相同 IoU 全并列，穷举 gold/prediction 四种输入顺序",
        "expected_secure": "所有顺序产生相同一对一映射",
        "input": {"gold_vehicles": gold, "predicted_vehicles": predictions},
        "observations": observations,
        "distinct_mappings": sorted(mappings),
        "verdict": "PASS" if len(mappings) == 1 else "FAIL",
    }


def main() -> None:
    results = run_cases()
    determinism = run_determinism()
    evidence = {
        "protocol": "read-only red-team of coord/evaluation-v3/evaluator.py",
        "network_or_model_calls": 0,
        "evaluator_sha256": sha256_file(EVALUATOR_PATH),
        "case_results": results,
        "determinism": determinism,
    }
    (HERE / "actual-results.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{'CASE':35} {'VERDICT':7} "
        f"{'QUANTITY':18} {'IDENTITY':18} ACTUAL"
    )
    for result in results:
        actual = result["actual"]
        if actual["kind"] == "report":
            q = actual["summary"]["quantity"]
            i = actual["summary"]["identity"]
            q_text = f"{q['numerator']}/{q['denominator']}={q['rate']}"
            i_text = f"{i['numerator']}/{i['denominator']}={i['rate']}"
            detail = ""
        else:
            q_text = "-"
            i_text = "-"
            detail = f"{actual['type']}: {actual['message']}"
        print(
            f"{result['case_id']:35} {result['verdict']:7} "
            f"{q_text:18} {i_text:18} {detail}"
        )
    print(
        f"{'A27-order-swap':35} {determinism['verdict']:7} "
        f"{'-':18} {'-':18} "
        f"distinct_mappings={len(determinism['distinct_mappings'])}"
    )
    fails = sum(result["verdict"] == "FAIL" for result in results)
    fails += determinism["verdict"] == "FAIL"
    print(f"\nfailures={fails}; evidence={HERE / 'actual-results.json'}")


if __name__ == "__main__":
    main()
