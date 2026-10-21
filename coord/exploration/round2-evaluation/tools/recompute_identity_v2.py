"""Independent offline recompute of legacy whole-vehicle identity-assembly-v2."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from core import (
    EvaluationError,
    evaluate_output,
    load_canonical_output,
    load_json,
    nearest_rank_p95,
    sha256_file,
    truth_map,
    write_json,
    write_text,
)


TIMES = (5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600)


def audit_manifest(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "EVIDENCE_MANIFEST.json")
    rows = []
    for file_row in manifest.get("files", []):
        path = root / file_row["path"]
        actual = sha256_file(path) if path.is_file() else None
        rows.append(
            {
                "path": file_row["path"],
                "exists": path.is_file(),
                "declared_sha256": file_row["sha256"],
                "actual_sha256": actual,
                "match": actual == file_row["sha256"],
            }
        )
    return {
        "schema": "round2-identity-evidence-audit-v1",
        "manifest_sha256": sha256_file(root / "EVIDENCE_MANIFEST.json"),
        "file_count": len(rows),
        "matches": sum(row["match"] for row in rows),
        "mismatches": [row for row in rows if not row["match"]],
        "all_match": bool(rows) and all(row["match"] for row in rows),
    }


def load_inputs(root: Path) -> dict[int, dict[str, Any]]:
    inputs = load_json(root / "INPUTS.json")
    rows = {}
    for sample in inputs.get("samples", []):
        time_s = int(sample["time"])
        if time_s in rows:
            raise EvaluationError(f"duplicate input time {time_s}")
        rows[time_s] = sample
    if tuple(sorted(rows)) != TIMES:
        raise EvaluationError(f"input times differ from frozen {TIMES}")
    return rows


def candidate_samples(
    root: Path, single_root: Path, inputs: dict[int, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    samples = []
    per_time = {}
    for time_s in TIMES:
        time_input = inputs[time_s]
        per_time[time_s] = {}
        for camera in ("north", "south"):
            source_info = time_input["cameras"][camera]
            source_rel = source_info["source_raw"]
            source_name = Path(str(source_rel).replace("\\", "/")).name
            source_path = single_root / "raw" / "B_aisle" / "r1" / source_name
            source = load_json(source_path)
            if sha256_file(source_path) != source_info["source_raw_sha256"]:
                raise EvaluationError(f"{source_path}: B r1 source hash mismatch")
            candidates = source_info["candidates"]
            ids = [candidate["id"] for candidate in candidates]
            if len(ids) != len(set(ids)):
                raise EvaluationError(f"t{time_s} {camera}: duplicate candidate IDs")
            vehicles = source.get("vehicles")
            if not isinstance(vehicles, list) or len(vehicles) != len(candidates):
                raise EvaluationError(
                    f"t{time_s} {camera}: candidate count differs from B r1 vehicles"
                )
            normalized_vehicles = []
            for candidate, vehicle in zip(candidates, vehicles):
                if candidate.get("source_index_1based") != len(normalized_vehicles) + 1:
                    raise EvaluationError(
                        f"t{time_s} {camera}: candidate source order mismatch"
                    )
                if candidate.get("bbox_aisle_norm") != vehicle.get("bbox"):
                    raise EvaluationError(
                        f"t{time_s} {camera}: candidate bbox differs from B r1"
                    )
                normalized_vehicles.append(
                    {
                        **vehicle,
                        "id": candidate["id"],
                    }
                )
            sample_id = f"{camera}_{time_s}"
            sample = {
                "sample_id": sample_id,
                "camera": camera,
                "time": time_s,
                "status": "valid",
                "predicted_count": len(normalized_vehicles),
                "vehicles": normalized_vehicles,
                "bbox_space": "aisle_norm_0_1",
                "call_count": 1 if camera == "north" else 0,
                "input_images": 2 if camera == "north" else 2,
            }
            samples.append(sample)
            per_time[time_s][camera] = sample
    return samples, per_time


def validate_time_output(
    time_s: int,
    raw: dict[str, Any],
    samples: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    north_ids = [
        vehicle["id"] for vehicle in samples[time_s]["north"]["vehicles"]
    ]
    south_ids = [
        vehicle["id"] for vehicle in samples[time_s]["south"]["vehicles"]
    ]
    matrix = raw.get("pair_matrix")
    matches = raw.get("proposed_matches")
    parsed = raw.get("result") or {}
    issues = []
    release_audit_issues = []
    decisions = Counter()
    seen_pairs = set()
    support_counts = []
    if raw.get("time") != time_s:
        issues.append(f"raw time {raw.get('time')} != {time_s}")
    if not raw.get("ok"):
        issues.append("transport/model result is not ok")
    if matrix is None and isinstance(raw.get("parsed"), dict):
        matrix = raw["parsed"].get("pair_matrix")
    if matches is None and isinstance(raw.get("parsed"), dict):
        matches = raw["parsed"].get("proposed_matches")
    if not isinstance(matrix, list):
        issues.append("pair_matrix is not a list")
        matrix = []
    if not isinstance(matches, list):
        matches = []
        issues.append("proposed_matches is not a list")

    for pair in matrix:
        if not isinstance(pair, dict):
            issues.append("non-object matrix row")
            continue
        pair_key = (pair.get("north_id"), pair.get("south_id"))
        if pair_key in seen_pairs:
            issues.append(f"duplicate matrix pair {pair_key}")
        seen_pairs.add(pair_key)
        if pair.get("north_id") not in north_ids:
            issues.append(f"unknown north candidate {pair.get('north_id')!r}")
        if pair.get("south_id") not in south_ids:
            issues.append(f"unknown south candidate {pair.get('south_id')!r}")
        decision = pair.get("decision")
        if decision not in {"same", "different", "unknown"}:
            issues.append(f"invalid matrix decision {decision!r}")
        else:
            decisions[decision] += 1
        if decision == "same":
            support = pair.get("support")
            support_counts.append(len(support) if isinstance(support, list) else 0)

    expected_pairs = {
        (north_id, south_id) for north_id in north_ids for south_id in south_ids
    }
    if seen_pairs != expected_pairs:
        issues.append(
            f"matrix is not complete Cartesian product: missing "
            f"{len(expected_pairs - seen_pairs)}, extra {len(seen_pairs - expected_pairs)}"
        )

    match_pairs = []
    seen_matches = set()
    for pair in matches:
        if not isinstance(pair, dict):
            issues.append("non-object proposed match")
            continue
        north_id = pair.get("north_id")
        south_id = pair.get("south_id")
        key = (north_id, south_id)
        if key in seen_matches:
            issues.append(f"duplicate proposed match {key}")
        seen_matches.add(key)
        if key not in expected_pairs:
            issues.append(f"match references unknown candidates {key}")
        matrix_row = next(
            (
                row
                for row in matrix
                if isinstance(row, dict)
                and row.get("north_id") == north_id
                and row.get("south_id") == south_id
            ),
            None,
        )
        if matrix_row is None or matrix_row.get("decision") != "same":
            issues.append(f"match {key} lacks same matrix decision")
        match_pairs.append({"north_id": north_id, "south_id": south_id})
    if len({pair["north_id"] for pair in match_pairs}) != len(match_pairs):
        issues.append("proposed matches are not one-to-one on north IDs")
    if len({pair["south_id"] for pair in match_pairs}) != len(match_pairs):
        issues.append("proposed matches are not one-to-one on south IDs")

    north_count = len(north_ids)
    south_count = len(south_ids)
    overlap = len(seen_matches)
    unique = north_count + south_count - overlap
    if parsed.get("north_count") not in (None, north_count):
        issues.append("result north_count differs from frozen candidates")
    if parsed.get("south_count") not in (None, south_count):
        issues.append("result south_count differs from frozen candidates")
    if parsed.get("overlap") not in (None, overlap):
        issues.append("result overlap differs from matches")
    if parsed.get("unique") not in (None, unique):
        issues.append("result unique differs from N+S-overlap")

    unreliable = raw.get("unreliable_candidates")
    if raw.get("unreliable_candidates") is None:
        unreliable = parsed.get("unreliable_candidates", [])
    if not isinstance(unreliable, list):
        unreliable = []
        issues.append("unreliable_candidates is not a list")
    review_required = raw.get("review_required")
    if review_required is None:
        review_required = bool(raw.get("review_reasons"))
    gate_candidate = (
        not issues
        and decisions.get("unknown", 0) == 0
        and not review_required
        and not unreliable
        and all(count >= 2 for count in support_counts)
    )
    reported_release = parsed.get("auto_released")
    release_decision = (
        "auto_release"
        if reported_release is True
        else "review"
        if reported_release is False
        else None
    )
    if not isinstance(reported_release, bool):
        release_audit_issues.append(
            "result does not report a boolean auto_released decision"
        )
    elif reported_release != gate_candidate:
        release_audit_issues.append(
            f"reported auto_released={reported_release} != independent "
            f"gate candidate {gate_candidate}"
        )
    record = {
        "time": time_s,
        "status": "valid" if not issues else "failed",
        "north_count": north_count,
        "south_count": south_count,
        "overlap": overlap,
        "unique": unique,
        "matches": match_pairs,
        # Score the route's actual decision. The independent gate recommendation
        # is reported beside it, never silently substituted for the original.
        "release_decision": release_decision,
        "matrix_pair_count": len(seen_pairs),
        "decisions": dict(decisions),
        "unknown_pair_count": decisions.get("unknown", 0),
        "same_support_counts": support_counts,
        "reported_auto_released": reported_release,
        "recomputed_gate_candidate": gate_candidate,
        "release_audit_issues": release_audit_issues,
        "issues": issues,
    }
    audit = {
        "time": time_s,
        "matrix_pair_count": len(seen_pairs),
        "expected_pair_count": len(expected_pairs),
        "match_count": len(match_pairs),
        "unknown_pair_count": decisions.get("unknown", 0),
        "same_pair_count": decisions.get("same", 0),
        "different_pair_count": decisions.get("different", 0),
        "gate_candidate": gate_candidate,
        "issues": issues,
        "release_audit_issues": release_audit_issues,
        "release_decision_matches_recomputed": (
            isinstance(reported_release, bool)
            and reported_release == gate_candidate
        ),
        "request_sha256": raw.get("request_sha256"),
    }
    return record, audit


def markdown(result: dict[str, Any]) -> str:
    independent = result["independent"]
    camera = independent["camera_count"]
    unique = independent["unique"]
    overlap = independent["overlap"]
    release = independent["release"]
    cost = result["performance"]
    def number(value: Any) -> str:
        return "未测" if value is None else f"{value:.3f}"
    return "\n".join(
        [
            "# identity-assembly-v2 独立复算（旧整车口径）",
            "",
            "**`legacy_whole_vehicle`：复用 B r1 整车候选并做跨机位装配，不能追认为 roof-only。**",
            "",
            f"- 机位计数（B r1 冻结，非新检测收益）：**{camera['headline']}**，"
            f"MAE {camera['mae']:.3f}，valid {camera['valid_n']}/20",
            f"- overlap：**{overlap['headline']}**，MAE {number(overlap['mae'])}",
            f"- unique：**{unique['headline']}**，MAE {number(unique['mae'])}",
            f"- 自动放行：{release['auto_released']}/{release['n_total']}，"
            f"正确 {release['correct']}，错误 **{release['errors']}**；"
            f"复核 {release['reviewed']}",
            f"- 10 raw、{independent['matrix_pair_count']} 个北×南矩阵行；"
            f"same {independent['decision_counts'].get('same', 0)}，"
            f"unknown {independent['decision_counts'].get('unknown', 0)}，"
            f"different {independent['decision_counts'].get('different', 0)}",
            f"- 证据 manifest：**{result['sources']['evidence_manifest']['matches']}/"
            f"{result['sources']['evidence_manifest']['file_count']}** hash 一致",
            "",
            "| 项目 | 调用 | 图像 | tokens | 均值秒 | p95秒 |",
            "|---|---:|---:|---:|---:|---:|",
            f"| 当前装配 | {cost['online']['calls']} | {cost['online']['images']} | "
            f"{cost['online']['tokens']} | {cost['online']['latency_mean_s']:.3f} | "
            f"{cost['online']['latency_p95_s']:.3f} |",
            f"| 历史 B 候选 | {cost['initialization']['calls']} | "
            f"{cost['initialization']['images']} | {cost['initialization']['tokens']} | "
            f"{cost['initialization']['latency_s']:.3f}（串行等价） | 未测 |",
            f"| 合计 | {cost['combined']['calls']} | {cost['combined']['images']} | "
            f"{cost['combined']['tokens']} | {cost['combined']['latency_s']}（串行等价） | 未测 |",
            "",
            f"耗时另含一次候选构建 {cost['preparation_s']:.3f} 秒；"
            "未把 workers=2 墙钟当串行总成本。",
            "",
            "**判定：旧整车候选装配负结果。unique/overlap 数量命中不等于 3 对身份正确；"
            "全车 ID precision/recall/IDF1 未测。**",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--single-pass-root", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    root = args.identity_root.resolve()
    single_root = args.single_pass_root.resolve()
    truth_path = args.truth.resolve()
    inputs = load_inputs(root)
    samples, sample_by_time = candidate_samples(root, single_root, inputs)
    time_records = {}
    time_audits = []
    latencies = []
    tokens = 0
    usage_total = 0
    for time_s in TIMES:
        raw_path = root / "raw" / f"t{time_s}.json"
        raw = load_json(raw_path)
        record, audit = validate_time_output(time_s, raw, sample_by_time)
        expected_request_sha = inputs[time_s].get("request_sha256")
        if expected_request_sha and raw.get("request_sha256") != expected_request_sha:
            record["issues"].append("request_sha256 differs from frozen input manifest")
            record["status"] = "failed"
        time_records[time_s] = record
        time_audits.append(audit)
        attempt_usage = raw.get("usage") or {}
        latency = raw.get("latency_total_s")
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))
        if isinstance(attempt_usage.get("total_tokens"), int):
            tokens += attempt_usage["total_tokens"]
            usage_total += attempt_usage["total_tokens"]
        sample_by_time[time_s]["north"]["tokens_total"] = int(
            attempt_usage.get("total_tokens", 0) or 0
        )
        sample_by_time[time_s]["north"]["latency_total_s"] = latency
        sample_by_time[time_s]["north"]["call_count"] = 1
        sample_by_time[time_s]["north"]["input_images"] = 2
        sample_by_time[time_s]["south"]["tokens_total"] = 0
        sample_by_time[time_s]["south"]["call_count"] = 0
        sample_by_time[time_s]["south"]["input_images"] = 2

    canonical = {
        "schema": "round2-canonical-output-v1",
        "route": {
            "id": "identity-assembly-v2-legacy-whole-vehicle",
            "owner": "identity_assembly_v2",
            "mechanism": "one cross-camera matrix over frozen B r1 whole-vehicle candidates",
            "status": "rejected_candidate",
            "evidence_scope": "legacy_whole_vehicle",
            "roof_constraint_eligible": False,
            "model": "doubao-seed-2-0-mini-260428",
        },
        "evidence_scope": "legacy_whole_vehicle",
        "samples": samples,
        "times": [time_records[time_s] for time_s in TIMES],
        "release_unit": "time",
        "workflow": load_json(root / "metrics.json").get("workflow_audit", {}),
        "cost": {
            "concurrency": 2,
            "online": {"calls": 10, "images": 40, "tokens": tokens},
            "initialization": {
                "calls": 20,
                "images": 20,
                "tokens": 94168,
                "latency_s": 392.73,
                "source": "frozen B r1 candidate bootstrap",
            },
        },
    }

    run = evaluate_output(
        truth_path,
        load_canonical_output_from_memory(canonical),
        split="dev",
        input_integrity={
            "all_match": audit_manifest(root)["all_match"]
            and all(not audit["issues"] for audit in time_audits),
            "identity_evidence_manifest_match": audit_manifest(root)["all_match"],
            "raw_times_valid": sum(not audit["issues"] for audit in time_audits),
        },
        baseline_exact=16,
    )
    # The loader is fed a temporary canonical reconstruction. Do not publish
    # that transient path as if it were a route-owned raw artifact.
    run["source"]["output_path"] = "in-memory canonical reconstruction"
    run["source"]["output_sha256"] = None

    metrics = load_json(root / "metrics.json")
    checks = {
        "camera_exact": run["camera_count"]["exact"] == 18,
        "camera_valid": run["camera_count"]["valid_n"] == 20,
        "overlap_exact": run["overlap"]["exact"] == 3,
        "overlap_mae": (
            run["overlap"]["mae"] is not None
            and abs(run["overlap"]["mae"] - 1.1) <= 1e-9
        ),
        "unique_exact": run["unique"]["exact"] == 2,
        "unique_mae": (
            run["unique"]["mae"] is not None
            and abs(run["unique"]["mae"] - 1.3) <= 1e-9
        ),
        "release_errors": run["release"]["errors"] == 5,
        "release_correct": run["release"]["correct"] == 1,
        "reported_auto_released": run["release"]["auto_released"] == 6,
        "reviewed": run["release"]["reviewed"] == 4,
        "matrix_pairs": sum(row["matrix_pair_count"] for row in time_audits) == 119,
        "all_matrix_complete": all(
            row["matrix_pair_count"] == row["expected_pair_count"]
            for row in time_audits
        ),
        "all_matches_valid": all(not row["issues"] for row in time_audits),
    }

    mean_latency = statistics.fmean(latencies) if latencies else None
    p95_latency = nearest_rank_p95(latencies)
    performance = {
        "online": {
            "calls": 10,
            "images": 40,
            "tokens": tokens,
            "latency_mean_s": round(mean_latency, 3) if mean_latency is not None else None,
            "latency_p95_s": p95_latency,
            "serial_equivalent_s": round(sum(latencies), 3),
            "concurrency": 2,
        },
        "initialization": {
            "calls": 20,
            "images": 20,
            "tokens": 94168,
            "latency_s": 392.73,
            "note": "previously paid B r1 bootstrap; required on a fresh video",
        },
        "combined": {
            "calls": 30,
            "images": 60,
            "tokens": tokens + 94168,
            "latency_s": round(sum(latencies) + 392.73, 3),
            "note": "online serial equivalent plus historical bootstrap; no fresh-video e2e measurement",
        },
        "preparation_s": metrics.get("cost", {}).get("preparation_s"),
        "peak_memory_mb": metrics.get("cost", {}).get("peak_memory_mb"),
        "wall_clock_online_s": metrics.get("cost", {}).get("actual_wall_s"),
    }
    result = {
        "schema": "round2-identity-v2-independent-recompute-v1",
        "evidence_scope": "legacy_whole_vehicle",
        "roof_constraint_eligible": False,
        "no_model_calls": True,
        "independent": {
            **run,
            "matrix_pair_count": sum(row["matrix_pair_count"] for row in time_audits),
            "decision_counts": dict(
                sum(
                    (Counter(row["decisions"]) for row in time_records.values()),
                    Counter(),
                )
            ),
            "time_audits": time_audits,
            "release_gate_audit": {
                "reported_released": sum(
                    row["reported_auto_released"] is True
                    for row in time_records.values()
                ),
                "reported_reviewed": sum(
                    row["reported_auto_released"] is False
                    for row in time_records.values()
                ),
                "independent_gate_candidates": sum(
                    row["recomputed_gate_candidate"]
                    for row in time_records.values()
                ),
                "decision_differences": [
                    {
                        "time": row["time"],
                        "reported_auto_released": row["reported_auto_released"],
                        "recomputed_gate_candidate": row[
                            "recomputed_gate_candidate"
                        ],
                        "issues": row["release_audit_issues"],
                    }
                    for row in time_records.values()
                    if not all(
                        not audit["release_audit_issues"]
                        for audit in time_audits
                        if audit["time"] == row["time"]
                    )
                ],
                "note": (
                    "Overlap/unique and release safety are separate. The route's "
                    "reported false decision remains a review; independent gate "
                    "differences are diagnostic, not a structural schema failure."
                ),
            },
        },
        "sources": {
            "identity_root": str(root),
            "single_pass_root": str(single_root),
            "truth_path": str(truth_path),
            "evidence_manifest": audit_manifest(root),
            "inputs_sha256": sha256_file(root / "INPUTS.json"),
            "metrics_sha256": sha256_file(root / "metrics.json"),
            "summary_sha256": sha256_file(root / "summary.json"),
            "run_timing_sha256": sha256_file(root / "RUN_TIMING.json"),
        },
        "declared_comparison": {
            "checks": checks,
            "all_match": all(checks.values()),
        },
        "performance": performance,
    }
    write_json(args.out_json, result)
    write_text(args.out_md, markdown(result))
    print(
        f"identity camera={run['camera_count']['headline']} "
        f"overlap={run['overlap']['headline']} unique={run['unique']['headline']} "
        f"release_errors={run['release']['errors']} declared_match={all(checks.values())}"
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
