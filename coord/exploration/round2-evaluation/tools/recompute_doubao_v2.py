"""Offline recompute of the legacy whole-vehicle doubao-v2 Mini benchmark.

This is explicitly NOT a roof-only result. It preserves the historical
0-1000 count-compatibility erratum and the separately preregistered strict
0-1 coordinate schema.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from core import (
    EvaluationError,
    evaluate_output,
    load_canonical_output,
    load_json,
    sha256_file,
    truth_map,
    write_json,
    write_text,
)


def b_normalize(parsed: Any) -> list[dict[str, Any]]:
    """Transcribe the frozen historical B normalization algorithm."""

    if not isinstance(parsed, dict) or not isinstance(parsed.get("vehicles"), list):
        return []
    normalized = []
    for item in parsed["vehicles"]:
        value = item.get("bbox") if isinstance(item, dict) else None
        if not (
            isinstance(value, list)
            and len(value) == 4
            and all(
                isinstance(number, (int, float))
                and not isinstance(number, bool)
                and math.isfinite(number)
                for number in value
            )
            and value[2] > value[0]
            and value[3] > value[1]
        ):
            continue
        bbox = [float(number) for number in value]
        largest = max(bbox)
        if largest > 1.2:
            if largest <= 1005:
                bbox = [number / 1000.0 for number in bbox]
            else:
                bbox = [
                    bbox[0] / 1040.0,
                    bbox[1] / 1920.0,
                    bbox[2] / 1040.0,
                    bbox[3] / 1920.0,
                ]
        if not (bbox[2] > bbox[0] and bbox[3] > bbox[1]):
            continue
        copy = dict(item)
        copy["bbox"] = [round(max(0.0, min(1.0, number)), 4) for number in bbox]
        normalized.append(copy)
    return normalized


def strict_schema(parsed: Any) -> tuple[bool, list[str]]:
    errors = []
    if not isinstance(parsed, dict):
        return False, ["parsed is not an object"]
    vehicles = parsed.get("vehicles")
    if not isinstance(vehicles, list):
        return False, ["vehicles is not a list"]
    counts = parsed.get("counts")
    declared = counts.get("total") if isinstance(counts, dict) else None
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
        errors.append("counts.total is not a non-negative integer")
    elif declared != len(vehicles):
        errors.append("counts.total != len(vehicles)")
    for index, item in enumerate(vehicles):
        bbox = item.get("bbox") if isinstance(item, dict) else None
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(
                isinstance(number, (int, float))
                and not isinstance(number, bool)
                and math.isfinite(number)
                and 0.0 <= float(number) <= 1.0
                for number in bbox
            )
            and bbox[2] > bbox[0]
            and bbox[3] > bbox[1]
        ):
            errors.append(f"invalid_normalized_bbox_{index}")
    return not errors, errors


def coordinate_class(parsed: Any) -> str:
    vehicles = parsed.get("vehicles") if isinstance(parsed, dict) else None
    if not isinstance(vehicles, list) or not vehicles:
        return "no_vehicles"
    values = []
    for vehicle in vehicles:
        bbox = vehicle.get("bbox") if isinstance(vehicle, dict) else None
        if not isinstance(bbox, list) or len(bbox) != 4:
            return "invalid"
        values.extend(float(number) for number in bbox)
    if all(0.0 <= value <= 1.0 for value in values):
        return "raw_0_1"
    if max(values) <= 1005.0:
        return "raw_0_1000"
    if all(-0.5 <= value <= 1050.0 for value in values[:0]):
        return "unreachable"
    if any(value > 1005.0 for value in values):
        return "raw_pixel_scale"
    return "invalid"


def audit_input_manifest(benchmark_root: Path, single_root: Path) -> dict[str, Any]:
    manifest = load_json(benchmark_root / "manifest.json")
    rows = []
    seen = Counter()
    for sample in manifest.get("samples", []):
        sample_id = sample.get("sample_id")
        seen[sample_id] += 1
        benchmark_path = benchmark_root / sample["image"]
        # The manifest stores a public-root-relative path.
        if not benchmark_path.is_file():
            benchmark_path = benchmark_root.parent.parent.parent / sample["image"]
        b_input = single_root / "inputs" / "aisle" / f"{sample_id}.jpg"
        benchmark_hash = sha256_file(benchmark_path) if benchmark_path.is_file() else None
        b_hash = sha256_file(b_input) if b_input.is_file() else None
        rows.append(
            {
                "sample_id": sample_id,
                "declared_sha256": sample.get("sha256"),
                "benchmark_path_actual_sha256": benchmark_hash,
                "public_aisle_sha256": b_hash,
                "matches_declared": benchmark_hash == sample.get("sha256"),
                "matches_b_input": b_hash == sample.get("b_frozen_sha256"),
                "all_three_equal": (
                    benchmark_hash
                    == b_hash
                    == sample.get("sha256")
                    == sample.get("b_frozen_sha256")
                ),
            }
        )
    return {
        "schema": "round2-doubao-v2-input-audit-v1",
        "manifest_path": str((benchmark_root / "manifest.json").resolve()),
        "manifest_sha256": sha256_file(benchmark_root / "manifest.json"),
        "sample_count": len(rows),
        "unique_sample_ids": len(seen),
        "duplicate_sample_ids": sorted(
            key for key, count in seen.items() if count > 1
        ),
        "all_three_equal": sum(row["all_three_equal"] for row in rows),
        "prompt_path": str((benchmark_root / "prompt_aisle.txt").resolve()),
        "prompt_sha256": sha256_file(benchmark_root / "prompt_aisle.txt"),
        "prompt_matches_frozen_b": (
            sha256_file(benchmark_root / "prompt_aisle.txt")
            == "52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab"
        ),
        "amendments": {
            "evaluation_amendment_sha256": sha256_file(
                benchmark_root / "EVALUATION_AMENDMENT.md"
            ),
            "stop_notice_sha256": sha256_file(benchmark_root / "STOP_NOTICE.md"),
        },
        "rows": rows,
        "all_match": (
            len(rows) == 20
            and len(seen) == 20
            and all(row["all_three_equal"] for row in rows)
            and sha256_file(benchmark_root / "prompt_aisle.txt")
            == "52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab"
        ),
    }


def audit_raw_manifest(benchmark_root: Path) -> dict[str, Any]:
    manifest = load_json(benchmark_root / "RAW_MANIFEST.json")
    files = []
    for row in manifest.get("files", []):
        path = benchmark_root / row["file"]
        actual = sha256_file(path) if path.is_file() else None
        files.append(
            {
                "file": row["file"],
                "declared_sha256": row["sha256"],
                "actual_sha256": actual,
                "match": actual == row["sha256"],
            }
        )
    return {
        "schema": "round2-doubao-v2-raw-manifest-audit-v1",
        "manifest_sha256": sha256_file(benchmark_root / "RAW_MANIFEST.json"),
        "file_count": len(files),
        "matches": sum(row["match"] for row in files),
        "mismatches": [row for row in files if not row["match"]],
        "all_match": bool(files) and all(row["match"] for row in files),
    }


def load_mini(
    benchmark_root: Path, truth_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    camera_truth, _, truth_meta = truth_map(truth_path)
    raw_dir = benchmark_root / "raw" / "mini"
    finals = sorted(
        path
        for path in raw_dir.glob("*.json")
        if not path.name.endswith(".started.json") and ".attempt" not in path.name
    )
    if len(finals) != 20:
        raise EvaluationError(f"{raw_dir}: expected 20 final sample files, found {len(finals)}")

    samples = []
    sample_map: dict[str, dict[str, Any]] = {}
    attempt_files: list[Path] = []
    strict_rows = []
    coordinate_classes: Counter[str] = Counter()
    problems: list[str] = []
    count_normalization_mismatches = []
    for path in finals:
        result = load_json(path)
        sample_id = result.get("sample_id")
        if sample_id != path.stem:
            problems.append(f"{path.name}: sample_id {sample_id!r} != filename")
        if sample_id in sample_map:
            raise EvaluationError(f"{raw_dir}: duplicate sample_id {sample_id}")
        truth_row = camera_truth.get(sample_id)
        if truth_row is None:
            raise EvaluationError(f"{raw_dir}: unknown sample {sample_id}")
        logical_calls = result.get("logical_calls")
        logical_calls = [str(value) for value in logical_calls] if isinstance(logical_calls, list) else []
        if len(logical_calls) != 1:
            problems.append(f"{sample_id}: expected one logical call")
        relative_attempt = logical_calls[-1] if logical_calls else None
        if result.get("attempt_files"):
            relative_attempt = result["attempt_files"][-1]
        if relative_attempt is None:
            problems.append(f"{sample_id}: no attempt file")
            attempt = {}
            attempt_path = None
        else:
            attempt_path = benchmark_root / relative_attempt
            if not attempt_path.is_file():
                problems.append(f"{sample_id}: missing attempt {relative_attempt}")
                attempt = {}
            else:
                attempt = load_json(attempt_path)
                attempt_files.append(attempt_path)

        parsed = attempt.get("parsed")
        normalized = b_normalize(parsed)
        raw_vehicles = parsed.get("vehicles") if isinstance(parsed, dict) else None
        counts = parsed.get("counts") if isinstance(parsed, dict) else None
        declared = counts.get("total") if isinstance(counts, dict) else None
        count_valid = (
            bool(attempt.get("http_ok"))
            and isinstance(raw_vehicles, list)
            and isinstance(declared, int)
            and not isinstance(declared, bool)
            and declared >= 0
            and declared == len(raw_vehicles) == len(normalized)
        )
        if count_valid and declared != result.get("predicted_count"):
            count_normalization_mismatches.append(
                {
                    "sample_id": sample_id,
                    "recomputed": declared,
                    "result_field": result.get("predicted_count"),
                }
            )
        strict_valid, strict_errors = strict_schema(parsed)
        coordinate_class_value = coordinate_class(parsed)
        coordinate_classes[coordinate_class_value] += 1
        strict_rows.append(
            {
                "sample_id": sample_id,
                "count_valid": count_valid,
                "strict_schema_valid": strict_valid,
                "strict_schema_errors": strict_errors,
                "raw_distribution": coordinate_class_value,
                "reported_valid": attempt.get("valid"),
                "reported_schema_errors": attempt.get("schema_errors"),
            }
        )

        status = "valid" if count_valid else "failed"
        samples.append(
            {
                "sample_id": sample_id,
                "camera": truth_row["camera"],
                "time": truth_row["time"],
                "status": status,
                "predicted_count": declared if count_valid else None,
                "vehicles": normalized,
                "bbox_space": "aisle_norm_0_1",
                "call_count": 1,
                "input_images": 1,
                "tokens_total": sum(
                    int((attempt.get("usage") or {}).get(field, 0) or 0)
                    for field in ("total_tokens",)
                ),
                "latency_total_s": attempt.get("latency_s"),
            }
        )
        sample_map[sample_id] = samples[-1]

    canonical = {
        "schema": "round2-canonical-output-v1",
        "route": {
            "id": "doubao-v2-mini-legacy-whole-vehicle",
            "owner": "new_doubao_benchmark_v2",
            "mechanism": "same frozen aisle image and whole-vehicle prompt with new Mini model",
            "status": "legacy_control",
            "evidence_scope": "legacy_whole_vehicle",
            "roof_constraint_eligible": False,
            "model": "doubao-seed-2-0-mini-260428",
        },
        "evidence_scope": "legacy_whole_vehicle",
        "samples": samples,
        "times": [],
        "cost": {
            "concurrency": 2,
            "online": {
                "calls": 20,
                "images": 20,
                "tokens": sum(sample["tokens_total"] for sample in samples),
            },
        },
        "workflow": {
            "human_boxes_used_as_model_input": False,
            "same_frame_annotations_exposed": False,
            "future_frames_exposed": False,
            "memory_retrieval_scope": "none",
            "previous_count_carryover": False,
            "failures_skipped": False,
            "failure_counted_in_denominator": True,
            "evidence": "manifest labels_in_requests=false and annotated_images_in_requests=false",
        },
    }

    valid_n = sum(row["count_valid"] for row in strict_rows)
    strict_valid_n = sum(
        row["strict_schema_valid"] and row["count_valid"] for row in strict_rows
    )
    return canonical, {
        "sample_count": len(strict_rows),
        "unique_sample_ids": len(sample_map),
        "problems": problems,
        "count_normalization_mismatches": count_normalization_mismatches,
        "count_valid_n": valid_n,
        "strict_valid_n": strict_valid_n,
        "coordinate_classes": dict(coordinate_classes),
        "strict_rows": strict_rows,
        "attempt_file_count": len(attempt_files),
        "truth_metadata": truth_meta,
    }, {
        "benchmark_root": str(benchmark_root.resolve()),
        "truth_path": str(truth_path.resolve()),
        "inputs": audit_input_manifest(benchmark_root, benchmark_root.parent / "single-pass"),
        "raw_manifest": audit_raw_manifest(benchmark_root),
    }


def compare_summary(
    summary: dict[str, Any],
    run_result: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    model = summary.get("models", {}).get("mini", {})
    camera = run_result["camera_count"]
    checks = {
        "exact": model.get("exact") == camera["exact"],
        "mae": (
            model.get("mae_valid") is not None
            and camera["mae"] is not None
            and abs(float(model["mae_valid"]) - camera["mae"]) <= 0.000501
        ),
        "valid_n": model.get("valid_N") == camera["valid_n"],
        "failures": model.get("failures") == camera["failed"],
        "under": model.get("undercount_units_valid") == camera["under_units"],
        "over": model.get("overcount_units_valid") == camera["over_units"],
        "strict_schema_valid_n": (
            model.get("strict_0to1_schema_valid_N") == audit["strict_valid_n"]
        ),
        "http_attempts": model.get("http_attempts") == 20,
        "http_successes": model.get("http_successes") == 20,
        "lite_not_run": summary["models"].get("lite", {}).get("attempted_N") == 0,
    }
    return {
        "schema": "round2-doubao-v2-summary-comparison-v1",
        "checks": checks,
        "all_match": all(checks.values()),
        "note": "MAE accepts declared three-decimal rounding only.",
    }


def markdown(result: dict[str, Any]) -> str:
    camera = result["independent"]["camera_count"]
    strict = result["independent"]["strict_schema"]
    cost = result["independent"]["cost"]
    return "\n".join(
        [
            "# doubao-v2 Mini 独立复算（旧整车口径）",
            "",
            "**证据口径：`legacy_whole_vehicle`。Mini 和 B 已看过整车外观，不能追认为 roof-only。**",
            "",
            f"- 固定 20 分母计数：**{camera['headline']}**，MAE {camera['mae']:.3f}，"
            f"valid {camera['valid_n']}/20，失败 {camera['failed']}，缺失 {camera['missing']}",
            f"- 0–1000 兼容计数 valid_N：**{strict['count_compat_valid_n']}/20**；"
            f"严格 0–1 schema valid_N：**{strict['strict_valid_n']}/20**；"
            f"严格 schema 下计数 correct：**{strict['strict_exact_fixed20']}/20**",
            f"- 输入 hash 20/20：**{result['sources']['inputs']['all_match']}**；"
            f"prompt 与 B 一致：**{result['sources']['inputs']['prompt_matches_frozen_b']}**",
            f"- 原始/attempt/started 文件 manifest："
            f"**{result['sources']['raw_manifest']['matches']}/"
            f"{result['sources']['raw_manifest']['file_count']}**",
            f"- Lite：**0/20 未运行**，无筛选或淘汰结论。",
            f"- 在线成本：20 调用、20 图、{cost['online_observed']['tokens']} tokens；"
            f"均值 {cost['online_observed']['latency_s_mean']} 秒，"
            f"p95 {cost['online_observed']['latency_s_p95_nearest_rank']} 秒。",
            "",
            "## 错误帧",
            "",
            *[
                f"- `{row['sample_id']}` {row['truth']}→{row['predicted']}"
                for row in camera["errors"]
            ],
            "",
            "## 坐标口径勘误",
            "",
            "冻结预注册勘误保留：B 兼容计数接受历史 0–1000 归一化；严格 0–1 schema 仍然失败，"
            "不能用兼容口径救回。原始分布：",
            "",
            *[
                f"- `{key}`：{value}"
                for key, value in sorted(strict["coordinate_classes"].items())
            ],
            "",
            f"与路线 summary 一致：**{result['declared_comparison']['all_match']}**。",
            "",
            "**判定：旧整车口径模型对照；不是车顶准确率，不是泛化，unique/overlap/身份/自动放行均未测。**",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-coordinate-audit", type=Path)
    args = parser.parse_args()

    benchmark_root = args.benchmark_root.resolve()
    canonical, audit, sources = load_mini(benchmark_root, args.truth.resolve())
    run = evaluate_output(
        args.truth.resolve(),
        load_canonical_output_from_memory(canonical),
        split="dev",
        input_integrity={
            "all_match": (
                sources["inputs"]["all_match"]
                and sources["raw_manifest"]["all_match"]
            ),
            "input_manifest_match": sources["inputs"]["all_match"],
            "raw_manifest_match": sources["raw_manifest"]["all_match"],
            "prompt_match": sources["inputs"]["prompt_matches_frozen_b"],
        },
        baseline_exact=16,
    )
    summary = load_json(benchmark_root / "summary.json")
    comparison = compare_summary(summary, run, audit)
    strict_exact = sum(
        row["count_valid"]
        and row["strict_schema_valid"]
        and next(
            (
                error["error"] == 0
                for error in run["camera_count"]["errors"]
                if error["sample_id"] == row["sample_id"]
            ),
            True,
        )
        for row in audit["strict_rows"]
    )
    strict = {
        "count_compat_policy": "EVALUATION_AMENDMENT.md / historical B normalize_vehicles",
        "count_compat_valid_n": audit["count_valid_n"],
        "strict_valid_n": audit["strict_valid_n"],
        "strict_schema_failures": 20 - audit["strict_valid_n"],
        "strict_exact_fixed20": strict_exact,
        "coordinate_classes": audit["coordinate_classes"],
        "rows": audit["strict_rows"],
    }
    result = {
        "schema": "round2-doubao-v2-independent-recompute-v1",
        "evidence_scope": "legacy_whole_vehicle",
        "roof_constraint_eligible": False,
        "no_model_calls": True,
        "independent": {
            **run,
            "strict_schema": strict,
            "audit": audit,
        },
        "sources": sources,
        "declared_comparison": comparison,
        "stopped_lite": {
            "status": "not_run",
            "coverage": "0/20",
            "reason": "user switched to roof-only before any Lite request",
        },
    }
    write_json(args.out_json, result)
    write_text(args.out_md, markdown(result))
    if args.out_coordinate_audit:
        write_json(args.out_coordinate_audit, strict)
    print(
        f"mini={run['camera_count']['headline']} "
        f"strict_valid={audit['strict_valid_n']}/20 "
        f"declared_match={comparison['all_match']}"
    )
    return 0


def load_canonical_output_from_memory(doc: dict[str, Any]) -> dict[str, Any]:
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", delete=False
    ) as handle:
        json.dump(doc, handle, ensure_ascii=False)
        temp_path = Path(handle.name)
    try:
        return load_canonical_output(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
