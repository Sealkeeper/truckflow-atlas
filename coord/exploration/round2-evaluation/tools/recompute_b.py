"""Independently recompute single-pass B from public raw files.

No network access, no model calls, no truth writes and no access to private
session directories. All paths are explicit CLI arguments.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from core import (
    BBOX_SPACES,
    EvaluationError,
    evaluate_output,
    load_canonical_output,
    load_json,
    nearest_rank_p95,
    normalize_bbox,
    sha256_file,
    truth_map,
    write_json,
    write_text,
)


RUN_TAGS = ("r1", "r2", "r3")


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _call_bbox_space(bbox: Any) -> str:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return "invalid"
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return "invalid"
    if all(0.0 <= value <= 1.0 for value in values):
        return "0_1"
    if all(0.0 <= value <= 1000.0 for value in values):
        return "0_1000"
    return "outside_0_1000"


def audit_inputs(single_root: Path, truth_path: Path) -> dict[str, Any]:
    inputs_doc = load_json(single_root / "INPUTS.json")
    samples = inputs_doc.get("samples", [])
    prompt_path = single_root / "prompt_aisle.txt"
    prompt_sha = sha256_file(prompt_path)
    expected_prompt = (
        "52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab"
    )
    camera_truth, _, truth_meta = truth_map(truth_path)

    rows = []
    seen_ids: Counter[str] = Counter()
    variant_mismatches: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = sample.get("sample_id")
        seen_ids[sample_id] += 1
        row = {
            "sample_id": sample_id,
            "camera": sample.get("camera"),
            "time": sample.get("time"),
            "truth": sample.get("truth"),
            "variants": {},
        }
        truth_row = camera_truth.get(sample_id)
        if truth_row is None or truth_row["value"] != sample.get("truth"):
            variant_mismatches.append(
                {
                    "sample_id": sample_id,
                    "field": "truth",
                    "manifest": sample.get("truth"),
                    "canonical": truth_row["value"] if truth_row else None,
                }
            )
        for variant in ("aisle", "full", "far"):
            expected = sample.get(f"{variant}_sha256")
            path = single_root / "inputs" / variant / f"{sample_id}.jpg"
            exists = path.is_file()
            actual = sha256_file(path) if exists else None
            matches = exists and actual == expected
            row["variants"][variant] = {
                "path": str(path),
                "exists": exists,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": matches,
            }
            if not matches:
                variant_mismatches.append(
                    {
                        "sample_id": sample_id,
                        "variant": variant,
                        "expected": expected,
                        "actual": actual,
                    }
                )
        rows.append(row)

    duplicate_input_ids = sorted(key for key, count in seen_ids.items() if count > 1)
    aisle_matches = sum(1 for row in rows if row["variants"]["aisle"]["match"])
    all_variant_matches = sum(
        1
        for row in rows
        if all(variant["match"] for variant in row["variants"].values())
    )
    prompt_match = prompt_sha == expected_prompt
    aisle_all_match = (
        len(rows) == 20
        and not duplicate_input_ids
        and aisle_matches == 20
        and prompt_match
    )
    all_match = (
        aisle_all_match
        and all_variant_matches == 20
        and not variant_mismatches
    )
    return {
        "schema": "round2-b-input-audit-v1",
        "inputs_json_sha256": sha256_file(single_root / "INPUTS.json"),
        "prompt_path": str(prompt_path),
        "prompt_sha256": prompt_sha,
        "prompt_expected_sha256": expected_prompt,
        "prompt_match": prompt_match,
        "sample_count": len(rows),
        "unique_sample_count": len(seen_ids),
        "duplicate_sample_ids": duplicate_input_ids,
        "aisle_hash_matches": aisle_matches,
        "aisle_all_match": aisle_all_match,
        "all_variant_hash_matches": all_variant_matches,
        "mismatches": variant_mismatches,
        "truth": truth_meta,
        "rows": rows,
        "all_match": all_match,
    }


def audit_raw_manifest(single_root: Path) -> dict[str, Any]:
    manifest = load_json(single_root / "RAW_MANIFEST.json")
    files = 0
    matches = 0
    missing = []
    hash_mismatches = []
    source_hash_mismatches = []
    by_config: dict[str, Counter[str]] = {}
    fallback_embedded = []
    for run in manifest.get("runs", []):
        config = run.get("config")
        tag = run.get("run")
        bucket = by_config.setdefault(str(config), Counter())
        for item in run.get("files", []):
            files += 1
            bucket["files"] += 1
            path = single_root / item["destination"]
            if not path.is_file():
                missing.append(str(path))
                continue
            actual = sha256_file(path)
            if actual == item["destination_sha256"]:
                matches += 1
                bucket["hash_matches"] += 1
            else:
                hash_mismatches.append(
                    {
                        "destination": item["destination"],
                        "expected": item["destination_sha256"],
                        "actual": actual,
                    }
                )
            if item["source_sha256"] != item["destination_sha256"]:
                source_hash_mismatches.append(item["destination"])
            if item.get("fallback_embedded"):
                fallback_embedded.append(
                    {
                        "config": config,
                        "run": tag,
                        "sample_id": item.get("sample_id"),
                    }
                )
    prompt = load_json(single_root / "B_evidence_manifest.json")
    return {
        "schema": "round2-b-raw-manifest-audit-v1",
        "manifest_sha256": sha256_file(single_root / "RAW_MANIFEST.json"),
        "declared_files": manifest.get("totals", {}).get("files"),
        "observed_files": files,
        "hash_matches": matches,
        "missing": missing,
        "hash_mismatches": hash_mismatches,
        "source_destination_hash_mismatches": source_hash_mismatches,
        "by_config": {key: dict(value) for key, value in sorted(by_config.items())},
        "fallback_embedded": fallback_embedded,
        "evidence_manifest_prompt_sha256": prompt.get("prompt_sha256"),
        "all_match": (
            not missing and not hash_mismatches and not source_hash_mismatches
        ),
    }


def audit_evidence_manifest(single_root: Path) -> dict[str, Any]:
    evidence = load_json(single_root / "B_evidence_manifest.json")
    rows = []
    for sample_id, block in sorted(evidence.get("keys", {}).items()):
        manifest_truth = block.get("truth")
        for run in block.get("runs", []):
            tag = run["run"]
            public_path = single_root / "raw" / "B_aisle" / tag / f"{sample_id}.json"
            actual_hash = sha256_file(public_path)
            raw = load_json(public_path)
            top_sha = run.get("raw_sha256")
            vehicles_equal = raw.get("vehicles") == run.get("vehicles")
            rows.append(
                {
                    "sample_id": sample_id,
                    "run": tag,
                    "raw_sha256_matches": actual_hash == top_sha,
                    "predicted_count_matches": (
                        raw.get("predicted_count") == run.get("predicted_count")
                    ),
                    "truth_matches": raw.get("truth") == manifest_truth,
                    "manifest_truth": manifest_truth,
                    "vehicles_equal": vehicles_equal,
                    "call_count_matches": (
                        raw.get("call_count") == run.get("call_count")
                    ),
                }
            )
    return {
        "schema": "round2-b-evidence-manifest-audit-v1",
        "manifest_sha256": sha256_file(single_root / "B_evidence_manifest.json"),
        "rows": rows,
        "all_match": all(
            row["raw_sha256_matches"]
            and row["predicted_count_matches"]
            and row["truth_matches"]
            and row["vehicles_equal"]
            and row["call_count_matches"]
            for row in rows
        ),
        "row_count": len(rows),
    }


def load_b_run(
    single_root: Path,
    tag: str,
    camera_truth: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = single_root / "raw" / "B_aisle" / tag
    files = sorted(run_dir.glob("*.json"))
    if len(files) != 20:
        raise EvaluationError(f"{run_dir}: expected 20 JSON files, found {len(files)}")

    samples = []
    sample_map: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    call_bbox_counts: Counter[str] = Counter()
    call_bbox_total = 0
    top_bbox_violations = 0
    top_bbox_total = 0
    parsed_count_mismatches = []
    reported_truth_mismatches = []
    image_issues = []
    possible_miss_true = 0
    per_sample_latencies = []
    per_sample_tokens = []

    for path in files:
        raw = load_json(path)
        sample_id = raw.get("sample_id")
        if sample_id != path.stem:
            issues.append(f"{path.name}: sample_id {sample_id!r} != filename")
        if sample_id in sample_map:
            raise EvaluationError(f"{run_dir}: duplicate sample_id {sample_id}")
        truth_row = camera_truth.get(sample_id)
        if truth_row is None:
            raise EvaluationError(f"{run_dir}: unknown sample {sample_id}")
        if raw.get("camera") != truth_row["camera"] or raw.get("time") != truth_row["time"]:
            issues.append(f"{sample_id}: camera/time do not match sample id")

        vehicles = raw.get("vehicles")
        if not isinstance(vehicles, list):
            issues.append(f"{sample_id}: vehicles is not a list")
            vehicles = []
        predicted = raw.get("predicted_count")
        if not isinstance(predicted, int) or isinstance(predicted, bool) or predicted < 0:
            issues.append(f"{sample_id}: invalid predicted_count {predicted!r}")
            predicted = None
        if predicted is not None and predicted != len(vehicles):
            issues.append(
                f"{sample_id}: predicted_count {predicted} != len(vehicles) "
                f"{len(vehicles)}"
            )
        if truth_row["value"] is not None and raw.get("truth") != truth_row["value"]:
            reported_truth_mismatches.append(
                {
                    "sample_id": sample_id,
                    "raw_truth": raw.get("truth"),
                    "canonical_truth": truth_row["value"],
                }
            )
        if (
            predicted is not None
            and truth_row["value"] is not None
            and raw.get("error") != predicted - truth_row["value"]
        ):
            issues.append(f"{sample_id}: stored error does not match recomputed error")

        calls = raw.get("calls")
        if not isinstance(calls, list):
            calls = []
        if raw.get("call_count") != len(calls):
            issues.append(
                f"{sample_id}: call_count {raw.get('call_count')} != calls {len(calls)}"
            )
        for call_index, call in enumerate(calls):
            parsed = call.get("parsed") or {}
            parsed_vehicles = parsed.get("vehicles")
            parsed_total = (parsed.get("counts") or {}).get("total")
            if (
                isinstance(parsed_vehicles, list)
                and parsed_total is not None
                and parsed_total != len(parsed_vehicles)
            ):
                parsed_count_mismatches.append(
                    {
                        "sample_id": sample_id,
                        "call_index": call_index,
                        "parsed_total": parsed_total,
                        "parsed_vehicles": len(parsed_vehicles),
                    }
                )
            for vehicle in parsed_vehicles or []:
                call_bbox_total += 1
                call_bbox_counts[_call_bbox_space(vehicle.get("bbox"))] += 1
            call_image = str(call.get("image", "")).replace("\\", "/")
            if call_image and Path(call_image).stem != sample_id:
                image_issues.append(
                    {"sample_id": sample_id, "call_image": call.get("image")}
                )

        images = raw.get("images")
        if not isinstance(images, list) or len(images) != 1:
            image_issues.append(
                {"sample_id": sample_id, "reason": "expected exactly one image", "images": images}
            )
        elif Path(str(images[0]).replace("\\", "/")).stem != sample_id:
            image_issues.append(
                {"sample_id": sample_id, "reason": "image stem mismatch", "images": images}
            )

        for instance in vehicles:
            top_bbox_total += 1
            _, _, error = normalize_bbox(instance.get("bbox"), "aisle_norm_0_1")
            if error:
                top_bbox_violations += 1
        coverage = raw.get("coverage") or {}
        possible_miss = bool(coverage.get("possible_miss"))
        if possible_miss:
            possible_miss_true += 1
        latency = raw.get("latency_total_s")
        tokens = raw.get("tokens_total")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            per_sample_latencies.append(float(latency))
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            per_sample_tokens.append(tokens)

        sample = {
            "sample_id": sample_id,
            "camera": truth_row["camera"],
            "time": truth_row["time"],
            "status": "failed" if raw.get("failure") else "valid",
            "predicted_count": predicted,
            "vehicles": vehicles,
            "bbox_space": "aisle_norm_0_1",
            "call_count": len(calls),
            "input_images": len(images) if isinstance(images, list) else 0,
            "tokens_total": tokens if isinstance(tokens, int) else 0,
            "latency_total_s": latency if isinstance(latency, (int, float)) else None,
            # Post-hoc reconstruction only. It is not a production-safe gate.
            "release_decision": not possible_miss,
        }
        samples.append(sample)
        sample_map[sample_id] = sample

    canonical = {
        "schema": "round2-canonical-output-v1",
        "route": {
            "id": f"single-pass-B-{tag}",
            "owner": "single-pass",
            "mechanism": "one frozen aisle image and prompt per camera sample",
            "status": "candidate",
            "evidence_scope": "legacy_whole_vehicle",
            "roof_constraint_eligible": False,
            "prompt_sha256": "52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab",
        },
        "evidence_scope": "legacy_whole_vehicle",
        "samples": samples,
        "times": [],
        "cost": {"concurrency": 1},
        "workflow": {
            "human_boxes_used_as_model_input": False,
            "same_frame_annotations_exposed": False,
            "future_frames_exposed": False,
            "memory_retrieval_scope": "none",
            "previous_count_carryover": False,
            "failures_skipped": False,
            "failure_counted_in_denominator": True,
            "evidence": (
                "Each raw references one exact target-time aisle image; public prompt "
                "contains no sample answer; no human-annotation path is consumed."
            ),
        },
    }
    audit = {
        "sample_count": len(samples),
        "unique_sample_ids": len(sample_map),
        "issues": issues,
        "call_bbox_counts": dict(call_bbox_counts),
        "call_bbox_total": call_bbox_total,
        "call_bbox_outside_0_1": (
            call_bbox_counts["0_1000"] + call_bbox_counts["outside_0_1000"]
        ),
        "top_bbox_total": top_bbox_total,
        "top_bbox_violations": top_bbox_violations,
        "parsed_count_mismatches": parsed_count_mismatches,
        "reported_truth_mismatches": reported_truth_mismatches,
        "image_issues": image_issues,
        "possible_miss_true": possible_miss_true,
        "latency_mean_s": _round(statistics.fmean(per_sample_latencies), 3)
        if per_sample_latencies
        else None,
        "latency_p95_nearest_rank_s": _round(
            nearest_rank_p95(per_sample_latencies), 3
        ),
        "tokens_total": sum(per_sample_tokens),
        "calls_total": sum(len(load_json(path).get("calls") or []) for path in files),
    }
    return canonical, audit


def _vehicle_summary(vehicle: dict[str, Any]) -> dict[str, Any]:
    bbox = vehicle.get("bbox")
    full = None
    if isinstance(bbox, list) and len(bbox) == 4:
        _, normalized, _ = normalize_bbox(bbox, "aisle_norm_0_1")
        if normalized:
            full = [
                350.0 + 520.0 * float(bbox[0]),
                960.0 * float(bbox[1]),
                350.0 + 520.0 * float(bbox[2]),
                960.0 * float(bbox[3]),
            ]
    return {
        "bbox_aisle_norm": bbox,
        "bbox_full_pixels": [_round(value, 3) for value in full] if full else None,
        "roof_color": vehicle.get("roof_color"),
        "cargo_color": vehicle.get("cargo_color"),
        "readable_text": vehicle.get("readable_text"),
        "visibility": vehicle.get("visibility"),
        "confidence": vehicle.get("confidence"),
    }


def counterexamples(
    single_root: Path, truth_path: Path
) -> dict[str, Any]:
    camera_truth, _, _ = truth_map(truth_path)
    checks: list[dict[str, Any]] = []

    r3_south = load_json(
        single_root / "raw" / "B_aisle" / "r3" / "south_2100.json"
    )
    white_record = next(
        (
            vehicle
            for vehicle in r3_south.get("vehicles", [])
            if "东风商用车"
            in " ".join(str(value) for value in vehicle.get("readable_text", []))
        ),
        None,
    )
    all_y2 = [
        float(vehicle["bbox"][3])
        for vehicle in r3_south.get("vehicles", [])
        if isinstance(vehicle.get("bbox"), list) and len(vehicle["bbox"]) == 4
    ]
    checks.append(
        {
            "id": "south_2100_r3_binding",
            "description": "white/东风商用车 claim lies in upper band while foreground white vehicle is below",
            "passes_reported_evidence": (
                white_record is not None
                and float(white_record["bbox"][3]) <= 0.45
                and bool(all_y2)
                and max(all_y2) <= 0.45
                and r3_south.get("predicted_count") == 4
                and camera_truth["south_2100"]["value"] == 3
            ),
            "white_record": _vehicle_summary(white_record) if white_record else None,
            "all_bbox_y2": all_y2,
            "truth": camera_truth["south_2100"]["value"],
            "predicted": r3_south.get("predicted_count"),
            "conclusion": (
                "Count 4 does not prove object-box-attribute binding. This is also "
                "a stable overcount across all three runs, not evidence of correct objects."
            ),
        }
    )

    r1_north = load_json(
        single_root / "raw" / "B_aisle" / "r1" / "north_600.json"
    )
    far_record = (
        r1_north["vehicles"][3] if len(r1_north.get("vehicles", [])) >= 4 else None
    )
    checks.append(
        {
            "id": "north_600_r1_color_support",
            "description": "count=4 but the farthest roof color claim is unsupported by visible evidence",
            "passes_reported_evidence": (
                far_record is not None
                and far_record.get("roof_color") == "黑色"
                and r1_north.get("predicted_count") == 4
                and camera_truth["north_600"]["value"] == 4
            ),
            "far_record": _vehicle_summary(far_record) if far_record else None,
            "truth": camera_truth["north_600"]["value"],
            "predicted": r1_north.get("predicted_count"),
            "conclusion": (
                "A correct total does not verify a deterministic color claim. "
                "Without an attribute gold set, no color accuracy rate is reported."
            ),
        }
    )

    ocr_rows = []
    for tag in RUN_TAGS:
        raw = load_json(
            single_root / "raw" / "B_aisle" / tag / "north_600.json"
        )
        for text in ("JT62649",):
            matches = [
                index
                for index, vehicle in enumerate(raw.get("vehicles", []))
                if text in vehicle.get("readable_text", [])
            ]
            ocr_rows.append(
                {
                    "run": tag,
                    "text": text,
                    "record_indices": matches,
                    "distinct_box_claims": len(matches),
                }
            )
    checks.append(
        {
            "id": "north_600_duplicate_ocr",
            "description": "same OCR string appears on two distinct vehicle records in every run",
            "passes_reported_evidence": all(
                len({tuple(load_json(single_root / 'raw' / 'B_aisle' / tag / 'north_600.json')['vehicles'][i]['bbox']) for i in row['record_indices']}) == 2
                for row, tag in zip(ocr_rows, RUN_TAGS)
            ),
            "rows": ocr_rows,
            "conclusion": (
                "Duplicate text is an identity/OCR risk, not proof that both readings "
                "are wrong. It cannot be used as a unique instance key."
            ),
        }
    )

    north5_predictions = [
        load_json(
            single_root / "raw" / "B_aisle" / tag / "north_5.json"
        ).get("predicted_count")
        for tag in RUN_TAGS
    ]
    checks.append(
        {
            "id": "north_5_instability",
            "description": "r1 exact total does not represent three-run stability",
            "passes_reported_evidence": (
                north5_predictions == [5, 4, 3]
                and camera_truth["north_5"]["value"] == 5
            ),
            "predictions": north5_predictions,
            "truth": camera_truth["north_5"]["value"],
            "conclusion": (
                "Report all runs 5/4/3. Do not select r1 after seeing the truth."
            ),
        }
    )
    return {
        "schema": "round2-b-counterexamples-v1",
        "all_machine_assertions_pass": all(
            row["passes_reported_evidence"] for row in checks
        ),
        "checks": checks,
        "scope_note": (
            "Machine checks verify published fields and geometry claims; semantic "
            "support still requires the cited images. No counterexample changes a label."
        ),
    }


def compare_declared(
    single_root: Path, run_results: dict[str, Any]
) -> dict[str, Any]:
    summary = load_json(single_root / "summary.json")
    runs_index = load_json(single_root / "RUNS_INDEX.json")
    declared_summary = {
        run["run"]: run
        for run in summary.get("configs", {}).get("B_aisle", {}).get("runs", [])
    }
    declared_index = {
        run.get("run", run.get("tag")): run["metrics"]
        for run in runs_index.get("runs", [])
        if run.get("config") == "B_aisle"
    }
    rows = []
    problems = []
    for tag in RUN_TAGS:
        actual = run_results[tag]["camera_count"]
        summary_row = declared_summary.get(tag, {})
        index_row = declared_index.get(tag, {})
        for source, declared in (("summary", summary_row), ("runs_index", index_row)):
            declared_mae = declared.get("mae")
            mae_matches = (
                actual["mae"] is not None
                and declared_mae is not None
                and abs(actual["mae"] - float(declared_mae)) <= 0.000501
            )
            row = {
                "run": tag,
                "source": source,
                "declared_exact": declared.get("exact"),
                "actual_exact": actual["exact"],
                "declared_mae": declared_mae,
                "actual_mae": actual["mae"],
                "declared_under": declared.get("undercount"),
                "actual_under": actual["under_units"],
                "declared_over": declared.get("overcount"),
                "actual_over": actual["over_units"],
                "declared_failures": declared.get("failures"),
                "actual_failed": actual["failed"],
                "exact_matches": declared.get("exact") == actual["exact"],
                "mae_matches_within_declared_rounding": mae_matches,
                "under_matches": declared.get("undercount") == actual["under_units"],
                "over_matches": declared.get("overcount") == actual["over_units"],
                "failures_match": declared.get("failures") == actual["failed"],
            }
            row["all_semantic_fields_match"] = all(
                row[key]
                for key in (
                    "exact_matches",
                    "mae_matches_within_declared_rounding",
                    "under_matches",
                    "over_matches",
                    "failures_match",
                )
            )
            if not row["all_semantic_fields_match"]:
                problems.append(row)
            rows.append(row)
    return {
        "schema": "round2-b-declared-comparison-v1",
        "rows": rows,
        "problems": problems,
        "note": (
            "MAE comparison permits the declared three-decimal rounding (<=0.000501). "
            "Exact, under, over and failure fields must match exactly."
        ),
    }


def recompute(
    single_root: Path, truth_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    camera_truth, _, truth_meta = truth_map(truth_path)
    inputs = audit_inputs(single_root, truth_path)
    raw_manifest = audit_raw_manifest(single_root)
    evidence = audit_evidence_manifest(single_root)
    runs = {}
    run_audits = {}
    for tag in RUN_TAGS:
        canonical, audit = load_b_run(single_root, tag, camera_truth)
        result = evaluate_output(
            truth_path,
            load_canonical_output_from_memory(canonical),
            split="dev",
            input_integrity={
                "all_match": inputs["aisle_all_match"],
                "aisle_hash_matches": inputs["aisle_hash_matches"],
                "unused_variants_complete": inputs["all_match"],
                "prompt_match": inputs["prompt_match"],
                "raw_manifest_match": raw_manifest["all_match"],
                "evidence_manifest_match": evidence["all_match"],
            },
            baseline_exact=16,
        )
        runs[tag] = result
        run_audits[tag] = audit

    declared = compare_declared(single_root, runs)
    attempts = load_json(single_root / "ATTEMPTS.json")
    release_total = {
        "auto_released": sum(run["release"]["auto_released"] for run in runs.values()),
        "correct": sum(run["release"]["correct"] for run in runs.values()),
        "errors": sum(run["release"]["errors"] for run in runs.values()),
        "reviewed": sum(run["release"]["reviewed"] for run in runs.values()),
        "refused": sum(run["release"]["refused"] for run in runs.values()),
        "truth_error_frames": sum(
            run["release"]["truth_error_frames"] for run in runs.values()
        ),
        "error_frames_caught_by_review": sum(
            run["release"]["error_frames_caught_by_review"] for run in runs.values()
        ),
    }
    release_total["review_rate"] = _round(release_total["reviewed"] / 60)
    release_total["false_release_rate"] = _round(
        release_total["errors"] / release_total["auto_released"]
        if release_total["auto_released"]
        else None
    )

    all_exact_18 = all(run["camera_count"]["exact"] == 18 for run in runs.values())
    all_20_valid = all(
        run["camera_count"]["valid_n"] == 20 for run in runs.values()
    )
    all_20_calls = all(
        run_audits[tag]["calls_total"] == 20 for tag in RUN_TAGS
    )
    all_counts_consistent = all(
        not run_audits[tag]["issues"] for tag in RUN_TAGS
    )
    all_no_failures = all(
        run["camera_count"]["failed"] == 0
        and run["camera_count"]["refused"] == 0
        and run["camera_count"]["missing"] == 0
        for run in runs.values()
    )
    all_top_bbox_0_1 = all(
        run_audits[tag]["top_bbox_violations"] == 0 for tag in RUN_TAGS
    )
    counter = counterexamples(single_root, truth_path)

    performance_rows = []
    for tag in RUN_TAGS:
        camera = runs[tag]["camera_count"]
        audit = run_audits[tag]
        performance_rows.append(
            {
                "run": tag,
                "calls": audit["calls_total"],
                "images": 20,
                "tokens": audit["tokens_total"],
                "latency_mean_s": audit["latency_mean_s"],
                "latency_p95_nearest_rank_s": audit[
                    "latency_p95_nearest_rank_s"
                ],
                "mae": camera["mae"],
                "exact": camera["exact"],
            }
        )
    meancost = {
        "calls_mean": _round(statistics.fmean(row["calls"] for row in performance_rows)),
        "images_mean": _round(statistics.fmean(row["images"] for row in performance_rows)),
        "tokens_total_mean": _round(
            statistics.fmean(row["tokens"] for row in performance_rows), 3
        ),
        "tokens_per_frame_mean": _round(
            statistics.fmean(row["tokens"] for row in performance_rows) / 20, 3
        ),
        "latency_mean_s": _round(
            statistics.fmean(row["latency_mean_s"] for row in performance_rows), 3
        ),
        "latency_p95_run_nearest_rank_s": nearest_rank_p95(
            row["latency_p95_nearest_rank_s"] for row in performance_rows
        ),
    }
    performance = {
        "schema": "round2-b-performance-v1",
        "per_run": performance_rows,
        "means": meancost,
        "initialization": {
            "available": False,
            "calls": None,
            "images": None,
            "tokens": None,
            "latency_s": None,
            "reason": (
                "B uses precomputed aisle crops; the public evidence does not record "
                "crop/init runtime, so initialization is not claimed to be free."
            ),
        },
        "combined_online_plus_initialization": None,
        "note": "Three runs are repeated executions of the same 20 frames, not 60 samples.",
    }
    result = {
        "schema": "round2-b-recompute-v2",
        "generated_at": "2026-10-21",
        "no_model_calls": True,
        "no_truth_writes": True,
        "sources": {
            "single_pass_root": str(single_root.resolve()),
            "truth_path": str(truth_path.resolve()),
            "truth_metadata": truth_meta,
            "inputs": inputs,
            "raw_manifest": raw_manifest,
            "evidence_manifest": evidence,
            "summary_sha256": sha256_file(single_root / "summary.json"),
            "runs_index_sha256": sha256_file(single_root / "RUNS_INDEX.json"),
            "attempts_sha256": sha256_file(single_root / "ATTEMPTS.json"),
            "attempts": {
                "frozen_evaluation": attempts.get("frozen_evaluation"),
                "total_http_requests": attempts.get("total_http_requests"),
                "retries": attempts.get("retries"),
                "failed_requests": attempts.get("failed_requests"),
                "warning": attempts.get("warning"),
            },
        },
        "runs": runs,
        "run_audits": run_audits,
        "aggregate": {
            "all_three_runs_exact_18": all_exact_18,
            "all_20_valid_each_run": all_20_valid,
            "one_call_per_sample_each_run": all_20_calls,
            "counts_and_lists_consistent": all_counts_consistent,
            "no_failures_refusals_or_missing": all_no_failures,
            "top_bbox_0_1": all_top_bbox_0_1,
            "per_call_bbox_outside_0_1": sum(
                run_audits[tag]["call_bbox_outside_0_1"] for tag in RUN_TAGS
            ),
            "possible_miss_true": sum(
                run_audits[tag]["possible_miss_true"] for tag in RUN_TAGS
            ),
            "release_posthoc": release_total,
            "counts_are_not_identity_proof": True,
            "unique_overlap_status": "not_measured_from_B_single-camera runs",
            "development_set_only": True,
        },
        "declared_comparison": declared,
        "counterexamples": counter,
        "performance": performance,
    }
    return result, inputs, raw_manifest, evidence


def load_canonical_output_from_memory(doc: dict[str, Any]) -> dict[str, Any]:
    """Write no file: normalize an in-memory B run through the same loader logic.

    The public evaluator only accepts an explicit file path. For B this helper
    writes a temporary file under the caller's system temp directory, uses the
    strict loader, then removes it. The raw source files are never modified.
    """

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


def markdown(result: dict[str, Any]) -> str:
    aggregate = result["aggregate"]
    lines = [
        "# 单遍 B 独立复算 v2",
        "",
        "本轮 **0 次模型调用**，只读取公共 raw、输入图、prompt 和用户终审真值；"
        "未修改标签或原路线文件。",
        "",
        "## 结论",
        "",
        f"- 三轮是否都为 18/20：**{aggregate['all_three_runs_exact_18']}**",
        f"- 每轮是否 20 valid / 20 调用 / 0 失败：**{aggregate['all_20_valid_each_run']} / "
        f"{aggregate['one_call_per_sample_each_run']} / {aggregate['no_failures_refusals_or_missing']}**",
        f"- 计数与实例列表长度一致：**{aggregate['counts_and_lists_consistent']}**",
        f"- 输入 aisle hash：**{result['sources']['inputs']['aisle_hash_matches']}/20**；"
        f"prompt hash：**{result['sources']['inputs']['prompt_match']}**",
        f"- 180 个公共 raw hash：**{result['sources']['raw_manifest']['hash_matches']}/"
        f"{result['sources']['raw_manifest']['observed_files']}**",
        f"- 自检 `possible_miss=true`：**{aggregate['possible_miss_true']}**；"
        f"事后放行错误：**{aggregate['release_posthoc']['errors']}**",
        f"- B 每次 parsed 框不在 0–1 的数量合计：**{aggregate['per_call_bbox_outside_0_1']}**"
        "（顶层输出已归一化）",
        "",
        "## 三轮固定分母",
        "",
        "| run | exact | MAE | 漏单位/帧 | 多单位/帧 | valid | failed | refused | missing | 调用 | tokens | 均值秒 | p95秒 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tag in RUN_TAGS:
        camera = result["runs"][tag]["camera_count"]
        perf = result["performance"]["per_run"]
        perf_row = next(row for row in perf if row["run"] == tag)
        lines.append(
            f"| {tag} | {camera['headline']} | {camera['mae']:.3f} | "
            f"{camera['under_units']}/{camera['under_frames']} | "
            f"{camera['over_units']}/{camera['over_frames']} | "
            f"{camera['valid_n']} | {camera['failed']} | {camera['refused']} | "
            f"{camera['missing']} | {perf_row['calls']} | {perf_row['tokens']} | "
            f"{perf_row['latency_mean_s']:.3f} | "
            f"{perf_row['latency_p95_nearest_rank_s']:.3f} |"
        )
    lines += [
        "",
        "三轮是同一 20 帧的重复运行，不是 60 个独立样本。",
        "",
        "## 错误帧",
        "",
    ]
    for tag in RUN_TAGS:
        errors = result["runs"][tag]["camera_count"]["errors"]
        formatted = ", ".join(
            f"`{row['sample_id']}` {row['truth']}→{row['predicted']}"
            for row in errors
        )
        lines.append(f"- {tag}: {formatted}")
    lines += [
        "",
        "## 自检放行复算（事后门禁，不是生产安全证明）",
        "",
        f"60 次运行样本中放行 {aggregate['release_posthoc']['auto_released']}，"
        f"正确 {aggregate['release_posthoc']['correct']}，错误 "
        f"{aggregate['release_posthoc']['errors']}；复核 "
        f"{aggregate['release_posthoc']['reviewed']}；错误帧被复核捕获 "
        f"{aggregate['release_posthoc']['error_frames_caught_by_review']}/"
        f"{aggregate['release_posthoc']['truth_error_frames']}。",
        "",
        "## 声明值差异",
        "",
    ]
    if result["declared_comparison"]["problems"]:
        lines.append(
            f"- 发现 {len(result['declared_comparison']['problems'])} 项差异，详见 JSON。"
        )
    else:
        lines.append("- 与 `summary.json`、`RUNS_INDEX.json` 的 exact/MAE/漏多/失败字段一致；"
                     "MAE 差异仅来自声明的三位小数舍入。")
    lines += [
        "",
        "## 可证反例与边界",
        "",
    ]
    for check in result["counterexamples"]["checks"]:
        lines.append(
            f"- `{check['id']}`：机器断言 "
            f"{'PASS' if check['passes_reported_evidence'] else 'FAIL'}。{check['conclusion']}"
        )
    lines += [
        "",
        "## 性能",
        "",
        f"三轮平均每轮 {result['performance']['means']['calls_mean']} 次调用、"
        f"{result['performance']['means']['images_mean']} 张图、"
        f"{result['performance']['means']['tokens_total_mean']} tokens；"
        f"帧均值 {result['performance']['means']['latency_mean_s']} 秒。"
        "历史裁剪/初始化耗时未公开记录，合并不伪造为 0。",
        "",
        "**判定：单遍 B 仍是计数研究候选，不是完整身份/框验收，也不是新时段泛化成绩。**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-pass-root", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-input-audit", type=Path)
    parser.add_argument("--out-raw-audit", type=Path)
    parser.add_argument("--out-evidence-audit", type=Path)
    args = parser.parse_args()

    result, inputs, raw_manifest, evidence = recompute(
        args.single_pass_root.resolve(), args.truth.resolve()
    )
    write_json(args.out_json, result)
    write_text(args.out_md, markdown(result))
    if args.out_input_audit:
        write_json(args.out_input_audit, inputs)
    if args.out_raw_audit:
        write_json(args.out_raw_audit, raw_manifest)
    if args.out_evidence_audit:
        write_json(args.out_evidence_audit, evidence)
    print(
        "B exact="
        + ",".join(str(result["runs"][tag]["camera_count"]["exact"]) for tag in RUN_TAGS)
        + " release_errors="
        + str(result["aggregate"]["release_posthoc"]["errors"])
        + " contract_problems="
        + str(len(result["declared_comparison"]["problems"]))
    )
    print(f"json={args.out_json.resolve()}")
    print(f"md={args.out_md.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
