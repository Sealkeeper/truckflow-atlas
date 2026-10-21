"""Evaluate per-model counts and consensus gates against the user's final truth.

Truth is read only from ``reviewed/user-final-review-v2-2026-10-21.json``.
The old ``data/gold/camera_counts_v0.json`` is never used here.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "accuracy" / "runs" / "consensus_v1"
DEFAULT_TRUTH = ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
CORE_MODELS = ["doubao", "aibox-deepseek-v4.1-flash", "aibox-glm-5.3-flash"]
ALL_MODELS = CORE_MODELS + ["zhipu"]
ERROR_FRAMES = ["north_300", "north_5", "north_600", "south_2100"]


def load_truth(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "truckflow-final-review-v2":
        raise SystemExit("expected truckflow-final-review-v2")
    truth: dict[str, int] = {}
    for row in payload["samples"]:
        if not row.get("completed"):
            continue
        seconds = int(row["time"])
        for camera in ("north", "south"):
            value = (row.get("camera_counts") or {}).get(camera)
            if isinstance(value, int):
                truth[f"{camera}_{seconds}"] = value
    return truth


def load_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sample_id = payload.get("sample_id") or path.stem
    record: dict[str, Any] = {
        "sample_id": sample_id,
        "ok": bool(payload.get("ok")),
        "latency_s": payload.get("latency_s"),
        "usage": payload.get("usage"),
        "attempts": payload.get("attempts"),
        "error": payload.get("error"),
        "status": payload.get("status"),
        "model_id": payload.get("model_id"),
    }
    parsed = payload.get("parsed") or {}
    counts = parsed.get("counts") or {}
    vehicles = parsed.get("vehicles") or []
    total = counts.get("total")
    record["count"] = int(total) if isinstance(total, int) else None
    record["vehicle_count"] = len(vehicles) if isinstance(vehicles, list) else None
    record["count_vehicle_mismatch"] = (
        record["count"] is not None
        and record["vehicle_count"] is not None
        and record["count"] != record["vehicle_count"]
    )
    record["uncertain"] = any(bool(item.get("uncertain")) for item in vehicles if isinstance(item, dict))
    record["uncertain_reasons"] = parsed.get("uncertain_reasons") or []
    record["scene_notes"] = parsed.get("scene_notes")
    if record["ok"] and record["count"] is None:
        record["ok"] = False
        record["error"] = "ok response without integer counts.total"
    return record


def load_model(runs: Path, model: str) -> dict[str, dict[str, Any]]:
    directory = runs / "raw" / model
    return {path.stem: load_result(path) for path in sorted(directory.glob("*.json"))}


def metric_block(truth: dict[str, int], records: dict[str, dict[str, Any]], samples: list[str]) -> dict[str, Any]:
    rows = []
    for sample in samples:
        record = records.get(sample)
        gold = truth[sample]
        if not record or not record.get("ok"):
            rows.append({"sample": sample, "gold": gold, "pred": None, "error": None, "ok": False})
            continue
        error = int(record["count"]) - gold
        rows.append(
            {
                "sample": sample,
                "gold": gold,
                "pred": int(record["count"]),
                "error": error,
                "ok": True,
                "uncertain": record.get("uncertain"),
                "latency_s": record.get("latency_s"),
            }
        )
    graded = [row for row in rows if row["ok"]]
    exact = sum(row["error"] == 0 for row in graded)
    mae = sum(abs(row["error"]) for row in graded) / len(graded) if graded else None
    return {
        "N": len(samples),
        "success": len(graded),
        "failed": len(samples) - len(graded),
        "exact": exact,
        "exact_rate": round(exact / len(graded) * 100, 1) if graded else None,
        "mae": round(mae, 3) if mae is not None else None,
        "under": sum(max(0, -row["error"]) for row in graded),
        "over": sum(max(0, row["error"]) for row in graded),
        "failed_samples": [row["sample"] for row in rows if not row["ok"]],
        "rows": rows,
    }


def model_cost(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items = list(records.values())
    ok = [item for item in items if item.get("ok")]
    latencies = [float(item["latency_s"]) for item in items if item.get("latency_s") is not None]
    success_latencies = [float(item["latency_s"]) for item in ok if item.get("latency_s") is not None]
    tokens = prompt = completion = reasoning = 0
    usage_calls = 0
    for item in items:
        usage = item.get("usage") or {}
        if not usage:
            continue
        usage_calls += 1
        tokens += int(usage.get("total_tokens") or 0)
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
        details = usage.get("completion_tokens_details") or {}
        reasoning += int(details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
    return {
        "calls": len(items),
        "success": len(ok),
        "failed": len(items) - len(ok),
        "mean_latency_s_all_calls": round(statistics.mean(latencies), 2) if latencies else None,
        "median_latency_s_all_calls": round(statistics.median(latencies), 2) if latencies else None,
        "mean_latency_s_success": round(statistics.mean(success_latencies), 2) if success_latencies else None,
        "serial_equivalent_s": round(sum(latencies), 2),
        "total_tokens": tokens,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "usage_calls": usage_calls,
        "total_count_vehicle_mismatches": sum(bool(item.get("count_vehicle_mismatch")) for item in ok),
    }


def consensus_decisions(
    truth: dict[str, int],
    records: dict[str, dict[str, dict[str, Any]]],
    samples: list[str],
    models: list[str],
    rule: str,
) -> list[dict[str, Any]]:
    decisions = []
    for sample in samples:
        votes = []
        missing = []
        uncertain_models = []
        for model in models:
            record = records[model].get(sample)
            if not record or not record.get("ok"):
                missing.append(model)
            else:
                votes.append((model, int(record["count"])))
                if record.get("uncertain"):
                    uncertain_models.append(model)

        reason = ""
        if missing:
            status = "review"
            value = None
            reason = "missing_model"
        else:
            counts = [count for _, count in votes]
            freq = Counter(counts)
            top_count, top_freq = freq.most_common(1)[0]
            unanimous = top_freq == len(models)

            if rule in {"unanimous", "strict_uncertainty"}:
                if unanimous:
                    status, value = "auto", top_count
                else:
                    status, value, reason = "review", None, "dissent"
            elif rule in {"majority", "majority_uncertainty"}:
                if top_freq >= 2:
                    status, value = "auto", top_count
                else:
                    status, value, reason = "review", None, "no_majority"
            else:
                raise ValueError(rule)

            if status == "auto" and rule in {"strict_uncertainty", "majority_uncertainty"} and uncertain_models:
                status, value, reason = "review", None, "uncertain_flag"

        gold = truth[sample]
        decisions.append(
            {
                "sample": sample,
                "gold": gold,
                "status": status,
                "value": value,
                "error": (value - gold) if value is not None else None,
                "reason": reason,
                "votes": {model: count for model, count in votes},
                "missing": missing,
                "uncertain_models": uncertain_models,
            }
        )
    return decisions


def consensus_summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(decisions)
    auto = [item for item in decisions if item["status"] == "auto"]
    review = [item for item in decisions if item["status"] == "review"]
    auto_correct = sum(item["error"] == 0 for item in auto)
    auto_wrong = sum(item["error"] != 0 for item in auto)
    abs_errors = [abs(item["error"]) for item in auto]
    return {
        "graded": total,
        "auto_released": len(auto),
        "auto_exact": auto_correct,
        "auto_errors": auto_wrong,
        "auto_error_frames": [item["sample"] for item in auto if item["error"] != 0],
        "auto_precision": round(auto_correct / len(auto) * 100, 1) if auto else None,
        "auto_coverage": round(len(auto) / total * 100, 1),
        "review_count": len(review),
        "review_rate": round(len(review) / total * 100, 1),
        "review_frames": [item["sample"] for item in review],
        "end_to_end_auto_exact": auto_correct,
        "end_to_end_auto_exact_rate": round(auto_correct / total * 100, 1),
        "auto_mae": round(sum(abs_errors) / len(auto), 3) if auto else None,
        "auto_error_abs_sum": sum(abs_errors),
        "errors_not_auto_counted": total - auto_correct,
        "upper_bound_if_review_always_correct": auto_correct + len(review),
        "upper_bound_exact_rate": round((auto_correct + len(review)) / total * 100, 1),
        "review_reasons": dict(Counter(item["reason"] for item in review)),
    }


def baseline_aisle_doubao(truth: dict[str, int]) -> dict[str, Any]:
    directory = ROOT / "accuracy" / "runs" / "aisle_doubao"
    records = {}
    for path in sorted(directory.glob("*_aisle.json")):
        if "grid_aisle" in path.name:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        first = next((run for run in payload.get("runs", []) if run.get("ok")), None)
        if not first:
            continue
        total = (first.get("parsed") or {}).get("counts", {}).get("total")
        if isinstance(total, int):
            records[path.stem.removesuffix("_aisle")] = {
                "ok": True,
                "count": total,
                "uncertain": False,
            }
    metrics = metric_block(truth, records, sorted(truth))
    metrics["source"] = "accuracy/runs/aisle_doubao/*_aisle.json only"
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument("--out", type=Path, default=DEFAULT_RUNS / "metrics.json")
    args = parser.parse_args()

    truth = load_truth(args.truth)
    samples = sorted(truth)
    records = {model: load_model(args.runs, model) for model in ALL_MODELS}

    per_model = {}
    for model in ALL_MODELS:
        block = metric_block(truth, records[model], samples)
        block["cost"] = model_cost(records[model])
        block["model_id"] = next(
            (item.get("model_id") for item in records[model].values() if item.get("model_id")),
            None,
        )
        per_model[model] = block

    coverage_path = args.runs / "coverage_2frames.json"
    coverage = None
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        for model, item in (coverage.get("per_model") or {}).items():
            if model in per_model:
                per_model[model]["coverage_2frames"] = {
                    "covered": item.get("covered"),
                    "marked": item.get("marked"),
                    "recall": item.get("recall"),
                    "scope": "north_600 + north_5 only; diagnostic, not 20-frame accuracy",
                }

    common_core = [
        sample
        for sample in samples
        if all(records[model].get(sample, {}).get("ok") for model in CORE_MODELS)
    ]
    common_all = [
        sample
        for sample in samples
        if all(records[model].get(sample, {}).get("ok") for model in ALL_MODELS)
    ]
    common_blocks = {
        "core_three": {
            "samples": common_core,
            "N": len(common_core),
            "models": {
                model: metric_block(truth, records[model], common_core) for model in CORE_MODELS
            },
        },
        "all_four": {
            "samples": common_all,
            "N": len(common_all),
            "models": {
                model: metric_block(truth, records[model], common_all) for model in ALL_MODELS
            },
        },
    }

    rules = {
        "R1_unanimous": consensus_summary(
            consensus_decisions(truth, records, samples, CORE_MODELS, "unanimous")
        ),
        "R2_two_of_three": consensus_summary(
            consensus_decisions(truth, records, samples, CORE_MODELS, "majority")
        ),
        "R3_any_dissent_or_uncertainty": consensus_summary(
            consensus_decisions(truth, records, samples, CORE_MODELS, "strict_uncertainty")
        ),
        "R4_two_of_three_plus_uncertainty": consensus_summary(
            consensus_decisions(truth, records, samples, CORE_MODELS, "majority_uncertainty")
        ),
        "S4_unanimous_including_zhipu": consensus_summary(
            consensus_decisions(truth, records, samples, ALL_MODELS, "unanimous")
        ),
        "R5_four_unanimous_plus_uncertainty": consensus_summary(
            consensus_decisions(truth, records, samples, ALL_MODELS, "strict_uncertainty")
        ),
    }
    detail = {
        "R1_unanimous": consensus_decisions(truth, records, samples, CORE_MODELS, "unanimous"),
        "R2_two_of_three": consensus_decisions(truth, records, samples, CORE_MODELS, "majority"),
        "R3_any_dissent_or_uncertainty": consensus_decisions(
            truth, records, samples, CORE_MODELS, "strict_uncertainty"
        ),
        "R4_two_of_three_plus_uncertainty": consensus_decisions(
            truth, records, samples, CORE_MODELS, "majority_uncertainty"
        ),
        "S4_unanimous_including_zhipu": consensus_decisions(
            truth, records, samples, ALL_MODELS, "unanimous"
        ),
        "R5_four_unanimous_plus_uncertainty": consensus_decisions(
            truth, records, samples, ALL_MODELS, "strict_uncertainty"
        ),
    }

    error_frame_table = {}
    for sample in ERROR_FRAMES:
        error_frame_table[sample] = {
            "gold": truth[sample],
            **{
                model: {
                    "pred": records[model].get(sample, {}).get("count"),
                    "ok": records[model].get(sample, {}).get("ok", False),
                    "uncertain": records[model].get(sample, {}).get("uncertain"),
                }
                for model in ALL_MODELS
            },
        }

    non_error_frames = [sample for sample in samples if sample not in ERROR_FRAMES]
    core_consensus = detail["R2_two_of_three"]
    non_error_rows = [item for item in core_consensus if item["sample"] in non_error_frames]
    four_error_rows = [item for item in core_consensus if item["sample"] in ERROR_FRAMES]
    safe_consensus = detail["R5_four_unanimous_plus_uncertainty"]
    safe_error_rows = [item for item in safe_consensus if item["sample"] in ERROR_FRAMES]
    safe_non_error_rows = [item for item in safe_consensus if item["sample"] in non_error_frames]

    cost = {
        "per_model": {model: per_model[model]["cost"] for model in ALL_MODELS},
        "core_three_serial_equivalent_s": round(
            sum(per_model[model]["cost"]["serial_equivalent_s"] for model in CORE_MODELS), 2
        ),
        "core_three_serial_equivalent_per_frame_s": round(
            sum(per_model[model]["cost"]["serial_equivalent_s"] for model in CORE_MODELS) / len(samples),
            2,
        ),
        "core_three_total_tokens": sum(
            per_model[model]["cost"]["total_tokens"] for model in CORE_MODELS
        ),
        "all_four_total_tokens": sum(per_model[model]["cost"]["total_tokens"] for model in ALL_MODELS),
        "currency": "not computed; no unit price supplied",
    }

    report = {
        "schema": "truckflow-consensus-evaluation-v1",
        "created_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "truth_file": str(args.truth.resolve()),
        "truth_samples": len(truth),
        "truth": truth,
        "models": CORE_MODELS,
        "fourth_vote": "zhipu",
        "per_model": per_model,
        "common_sets": common_blocks,
        "consensus_rules": rules,
        "consensus_detail": detail,
        "error_frames": error_frame_table,
        "majority_four_error_frames": four_error_rows,
        "majority_non_error_frames": non_error_rows,
        "majority_non_error_exact": sum(item["error"] == 0 for item in non_error_rows),
        "majority_non_error_count": len(non_error_rows),
        "four_model_safe_error_frames": safe_error_rows,
        "four_model_safe_non_error_frames": safe_non_error_rows,
        "baseline_aisle_doubao": baseline_aisle_doubao(truth),
        "coverage_2frames": coverage,
        "cost": cost,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"truth={len(truth)} core_common={len(common_core)} all_common={len(common_all)}")
    for model in ALL_MODELS:
        block = per_model[model]
        print(
            f"{model:<30} ok={block['success']}/{block['N']} exact={block['exact']}/{block['success']} "
            f"mae={block['mae']} under={block['under']} over={block['over']}"
        )
    for name, summary in rules.items():
        print(
            f"{name:<34} auto={summary['auto_released']}/{summary['graded']} "
            f"auto_exact={summary['auto_exact']} auto_errors={summary['auto_errors']} "
            f"review={summary['review_count']} auto_mae={summary['auto_mae']}"
        )
    print(f"error frames: {json.dumps(error_frame_table, ensure_ascii=False)}")
    print(f"metrics: {args.out}")


if __name__ == "__main__":
    main()
