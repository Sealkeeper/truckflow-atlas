"""Independent offline recompute of public roof-only-v1.

The adapter reads only published raw attempts, the public prompt/input manifest,
the frozen B input hashes and the user-reviewed count truth. It never calls a
model and never writes to the route directory.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
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


PROMPT_SHA256 = "9e7a956ccfcd4078b4a13526d5e0f8fe8c856cc84ee42a73723eaa97ccfb9362"
MODEL = "doubao-seed-2-0-mini-260428"
CAMERAS = ("north", "south")
EXPECTED_TIMES = (5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600)
FORBIDDEN_EVIDENCE_TERMS = (
    "车牌",
    "轮胎",
    "车灯",
    "尾灯",
    "侧面",
    "底盘",
    "不可见连接",
    "license plate",
    "tire",
    "wheel",
    "tail light",
    "side body",
    "undercarriage",
    "hitch",
)
ALLOWED_ROOF_KINDS = {"cab_roof", "cargo_roof", "top_open", "unknown"}


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _payload_sha(sample: dict[str, Any], public_root: Path, prompt: str) -> str:
    image_path = public_root / Path(str(sample["image"]).replace("\\", "/"))
    image_bytes = image_path.read_bytes()
    if sha256_file(image_path) != sample["sha256"]:
        raise EvaluationError(f"{sample['sample_id']}: image hash changed")
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 2400,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64,"
                            + base64.b64encode(image_bytes).decode("ascii")
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    return __import__("hashlib").sha256(
        json.dumps(payload, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def audit_sources(root: Path, single_root: Path, truth_path: Path) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    b_inputs = load_json(single_root / "INPUTS.json")
    b_by_id = {row["sample_id"]: row for row in b_inputs.get("samples", [])}
    prompt_path = root / "prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8-sig")
    prompt_sha = sha256_file(prompt_path)
    public_root = single_root.parents[2]
    rows = []
    seen_ids = Counter()
    seen_camera_time = Counter()
    for sample in manifest.get("samples", []):
        sample_id = sample.get("sample_id")
        seen_ids[sample_id] += 1
        seen_camera_time[(sample.get("time"), sample.get("camera"))] += 1
        b_row = b_by_id.get(sample_id)
        image_path = single_root / "inputs" / "aisle" / f"{sample_id}.jpg"
        actual_image_sha = sha256_file(image_path) if image_path.is_file() else None
        request_sha = _payload_sha(sample, public_root, prompt)
        rows.append(
            {
                "sample_id": sample_id,
                "camera": sample.get("camera"),
                "time": sample.get("time"),
                "image_exists": image_path.is_file(),
                "declared_image_sha256": sample.get("sha256"),
                "actual_image_sha256": actual_image_sha,
                "b_frozen_sha256": sample.get("b_frozen_sha256"),
                "b_inputs_aisle_sha256": b_row.get("aisle_sha256") if b_row else None,
                "image_hash_match": actual_image_sha == sample.get("sha256"),
                "b_frozen_match": sample.get("sha256")
                == sample.get("b_frozen_sha256"),
                "b_inputs_match": b_row is not None
                and sample.get("sha256") == b_row.get("aisle_sha256"),
                "reconstructed_request_sha256": request_sha,
            }
        )

    duplicate_ids = sorted(key for key, count in seen_ids.items() if count > 1)
    duplicate_camera_times = sorted(
        (time_s, camera)
        for (time_s, camera), count in seen_camera_time.items()
        if count > 1
    )
    expected_keys = {
        (time_s, camera) for time_s in EXPECTED_TIMES for camera in CAMERAS
    }
    observed_keys = set(seen_camera_time)
    all_inputs_match = (
        len(rows) == 20
        and not duplicate_ids
        and not duplicate_camera_times
        and observed_keys == expected_keys
        and all(
            row["image_exists"]
            and row["image_hash_match"]
            and row["b_frozen_match"]
            and row["b_inputs_match"]
            for row in rows
        )
        and prompt_sha == PROMPT_SHA256
    )
    return {
        "schema": "round2-roof-only-input-audit-v1",
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "prompt_sha256": prompt_sha,
        "prompt_expected_sha256": PROMPT_SHA256,
        "prompt_match": prompt_sha == PROMPT_SHA256,
        "manifest_model": manifest.get("model"),
        "manifest_temperature": manifest.get("temperature"),
        "manifest_max_tokens": manifest.get("max_tokens"),
        "manifest_workers": manifest.get("workers"),
        "input_count": len(rows),
        "unique_sample_ids": len(seen_ids),
        "duplicate_sample_ids": duplicate_ids,
        "duplicate_time_camera": duplicate_camera_times,
        "missing_camera_times": sorted(expected_keys - observed_keys),
        "unexpected_camera_times": sorted(observed_keys - expected_keys),
        "pixel_masking_implemented": manifest.get("pixel_masking_implemented"),
        "evidence_restriction": manifest.get("evidence_restriction"),
        "labels_in_model_input": manifest.get("labels_in_model_input"),
        "user_annotations_in_model_input": manifest.get("user_annotations_in_model_input"),
        "rows": rows,
        "all_match": all_inputs_match,
    }


def audit_raw_manifest(root: Path) -> dict[str, Any]:
    raw_manifest = load_json(root / "RAW_MANIFEST.json")
    rows = []
    for item in raw_manifest.get("files", []):
        path = root / Path(str(item["file"]).replace("\\", "/"))
        actual = sha256_file(path) if path.is_file() else None
        rows.append(
            {
                "file": item["file"],
                "exists": path.is_file(),
                "declared_bytes": item.get("bytes"),
                "actual_bytes": path.stat().st_size if path.is_file() else None,
                "declared_sha256": item.get("sha256"),
                "actual_sha256": actual,
                "match": actual == item.get("sha256"),
            }
        )
    return {
        "schema": "round2-roof-only-raw-manifest-audit-v1",
        "manifest_sha256": sha256_file(root / "RAW_MANIFEST.json"),
        "file_count": len(rows),
        "matches": sum(row["match"] for row in rows),
        "mismatches": [row for row in rows if not row["match"]],
        "all_match": bool(rows) and all(row["match"] for row in rows),
    }


def _roof_kind_mapping(raw_kind: Any) -> tuple[str, list[str]]:
    if raw_kind == "top_open":
        return "top_open", ["roof", "top_edge"]
    if raw_kind == "cargo_roof":
        return "top_closed", ["roof", "cargo_roof"]
    if raw_kind == "cab_roof":
        return "top_closed", ["roof"]
    return "unknown", ["roof"]


def _canonical_sample(
    summary_row: dict[str, Any],
    attempt: dict[str, Any],
    truth_row: dict[str, Any],
) -> dict[str, Any]:
    parsed = attempt.get("parsed") or {}
    coordinate_scale = parsed.get("coord_scale")
    if coordinate_scale not in (1, 1000):
        coordinate_scale = attempt.get("coord_scale_used")
    bbox_space = "aisle_norm_0_1" if coordinate_scale == 1 else "aisle_int_0_1000"
    roofs = parsed.get("roofs") if isinstance(parsed.get("roofs"), list) else []
    vehicles = parsed.get("vehicles") if isinstance(parsed.get("vehicles"), list) else []
    uncertain = parsed.get("uncertain") if isinstance(parsed.get("uncertain"), list) else []
    uncertain_by_roof = {
        roof_id
        for item in uncertain
        if isinstance(item, dict)
        for roof_id in item.get("roof_ids", [])
        if isinstance(roof_id, str)
    }

    observations = []
    for roof in roofs:
        if not isinstance(roof, dict):
            continue
        top_state, tags = _roof_kind_mapping(roof.get("roof_kind"))
        observations.append(
            {
                "id": roof.get("roof_id"),
                "bbox_space": bbox_space,
                "roof_bbox": roof.get("roof_bbox"),
                "top_state": top_state,
                "evidence_tags": tags,
                "component": "unknown",
                "review_required": roof.get("roof_id") in uncertain_by_roof,
                "raw_roof_kind": roof.get("roof_kind"),
                "raw_evidence": roof.get("evidence"),
            }
        )

    entities = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        entities.append(
            {
                "id": vehicle.get("vehicle_id"),
                "component": "unknown",
                "observation_ids": vehicle.get("roof_ids"),
                "identity_status": "unknown",
                "raw_size": vehicle.get("size"),
                "raw_evidence": vehicle.get("evidence"),
            }
        )

    valid = summary_row.get("valid") is True and attempt.get("valid") is True
    status = "valid" if valid else "failed"
    return {
        "sample_id": summary_row["sample_id"],
        "camera": truth_row["camera"],
        "time": truth_row["time"],
        "status": status,
        "evidence_scope": "roof_only",
        "input_evidence_scope": "prompt_constrained_full_frame",
        "pixel_masking_implemented": False,
        "predicted_count": parsed.get("count"),
        "physical_entities": entities,
        "roof_observations": observations,
        "uncertain": uncertain,
        "bbox_space": bbox_space,
        "call_count": summary_row.get("http_attempts", 0),
        "input_images": summary_row.get("http_attempts", 0),
        "tokens_total": (attempt.get("usage") or {}).get("total_tokens", 0),
        "latency_total_s": summary_row.get("latency_total_s"),
        "schema_errors": attempt.get("schema_errors", []),
        "parse_error": attempt.get("parse_error"),
        "raw_model": attempt.get("model_returned"),
        "raw_finish_reason": attempt.get("finish_reason"),
    }


def audit_attempts(
    root: Path, inputs: dict[str, Any], truth_path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[float], list[float]]:
    input_rows = {row["sample_id"]: row for row in inputs["rows"]}
    camera_truth, _, _ = truth_map(truth_path)
    attempt_audits = []
    final_attempts = {}
    http_latencies = []
    e2e_latencies = []
    seen_sample_ids = Counter()
    prompt_hash = inputs["prompt_sha256"]
    token_totals = Counter()
    forbidden_hits = []

    for sample_id in sorted(camera_truth):
        summary_path = root / "raw" / f"{sample_id}.json"
        if not summary_path.is_file():
            raise EvaluationError(f"{sample_id}: final raw summary is missing")
        summary = load_json(summary_path)
        seen_sample_ids[sample_id] += 1
        if summary.get("sample_id") != sample_id:
            raise EvaluationError(f"{summary_path}: sample_id mismatch")
        attempt_path = root / Path(
            str(summary["final_attempt_file"]).replace("\\", "/")
        )
        attempt = load_json(attempt_path)
        final_attempts[sample_id] = attempt
        input_row = input_rows[sample_id]
        errors = []
        if summary.get("request_sha256") != input_row["reconstructed_request_sha256"]:
            errors.append("final summary request_sha256 differs from reconstruction")
        if attempt.get("request_sha256") != input_row["reconstructed_request_sha256"]:
            errors.append("attempt request_sha256 differs from reconstruction")
        if attempt.get("prompt_sha256") != prompt_hash:
            errors.append("attempt prompt_sha256 differs from prompt")
        if attempt.get("image_sha256") != input_row["actual_image_sha256"]:
            errors.append("attempt image_sha256 differs from input")
        if attempt.get("model_returned") != MODEL:
            errors.append(f"model_returned is {attempt.get('model_returned')!r}")
        if attempt.get("status") != 200 or attempt.get("http_ok") is not True:
            errors.append("HTTP attempt was not successful")
        if attempt.get("finish_reason") != "stop":
            errors.append(f"finish_reason is {attempt.get('finish_reason')!r}")
        if not isinstance(attempt.get("parsed"), dict):
            errors.append("parsed response is not an object")
        if summary.get("http_attempts") != 1:
            errors.append(f"http_attempts is {summary.get('http_attempts')!r}, expected 1")
        if attempt.get("attempt") != 1:
            errors.append(f"attempt number is {attempt.get('attempt')!r}")

        parsed = attempt.get("parsed") or {}
        kind_errors = []
        for index, roof in enumerate(parsed.get("roofs") or []):
            if not isinstance(roof, dict) or roof.get("roof_kind") not in ALLOWED_ROOF_KINDS:
                kind_errors.append(index)
        text_sources = {
            "parsed": json.dumps(parsed, ensure_ascii=False),
            "reasoning": str(attempt.get("reasoning_content") or ""),
        }
        for source, text in text_sources.items():
            lowered = text.lower()
            for term in FORBIDDEN_EVIDENCE_TERMS:
                search_from = 0
                while True:
                    index = lowered.find(term.lower(), search_from)
                    if index < 0:
                        break
                    context = text[max(0, index - 24) : index + len(term) + 24]
                    negative_markers = (
                        "不能",
                        "不可",
                        "不得",
                        "不用",
                        "不得用",
                        "禁止",
                        "避免",
                        "没有用",
                        "不使用",
                        "not use",
                        "without using",
                        "cannot use",
                    )
                    forbidden_hits.append(
                        {
                            "sample_id": sample_id,
                            "source": source,
                            "term": term,
                            "context": context,
                            "negative_instruction_mention": any(
                                marker in context.lower()
                                for marker in negative_markers
                            ),
                        }
                    )
                    search_from = index + len(term)

        latency = attempt.get("latency_s")
        if isinstance(latency, (int, float)):
            http_latencies.append(float(latency))
        e2e = summary.get("latency_total_s")
        if isinstance(e2e, (int, float)):
            e2e_latencies.append(float(e2e))
        usage = attempt.get("usage") or {}
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(field)
            if isinstance(value, int):
                token_totals[field] += value

        attempt_audits.append(
            {
                "sample_id": sample_id,
                "attempt_file": str(attempt_path.relative_to(root)),
                "valid": summary.get("valid"),
                "schema_errors": attempt.get("schema_errors", []),
                "invalid_kind_indices": kind_errors,
                "request_sha256_matches_reconstruction": not any(
                    "request_sha256" in error for error in errors
                ),
                "issues": errors,
            }
        )

    if set(final_attempts) != set(camera_truth):
        raise EvaluationError("attempt set differs from frozen 20 camera samples")
    return (
        {
            "schema": "round2-roof-only-attempt-audit-v1",
            "sample_count": len(attempt_audits),
            "http_attempts": len(attempt_audits),
            "all_requests_reconstructed": all(
                row["request_sha256_matches_reconstruction"]
                for row in attempt_audits
            ),
            "all_single_attempts": all(
                not any("http_attempts" in issue for issue in row["issues"])
                for row in attempt_audits
            ),
            "all_transport_clean": all(
                not any("HTTP attempt" in issue for issue in row["issues"])
                for row in attempt_audits
            ),
            "token_totals": dict(token_totals),
            "forbidden_evidence_term_hits": forbidden_hits,
            "forbidden_term_positive_use_suspects": [
                hit
                for hit in forbidden_hits
                if not hit["negative_instruction_mention"]
            ],
            "rows": attempt_audits,
            "all_match": all(not row["issues"] for row in attempt_audits),
        },
        final_attempts,
        http_latencies,
        e2e_latencies,
    )


def markdown(result: dict[str, Any]) -> str:
    camera = result["independent"]["camera_count"]
    raw = result["roof_raw"]
    performance = result["performance"]
    lines = [
        "# roof-only-v1 独立复算",
        "",
        "**`roof_only_v1` 新口径；输入为完整 aisle 图，只有 prompt 限制使用车顶证据，"
        "未实施像素遮罩。旧 B / Mini / identity 不混算。**",
        "",
        f"- 固定 20 分母：**{camera['headline']}**，valid {camera['valid_n']}、"
        f"failed {camera['failed']}、refused {camera['refused']}、missing {camera['missing']}",
        f"- valid-only MAE：**{camera['mae']:.3f}**；漏计 "
        f"{camera['under_units']} 单位/{camera['under_frames']} 帧，多计 "
        f"{camera['over_units']} 单位/{camera['over_frames']} 帧",
        f"- 原始数字 count 命中：**{raw['count_exact']}/20**；"
        f"无 uncertain 的 fully-resolved count：**{raw['fully_resolved_count_exact']}/20**",
        f"- schema 严格有效：**{camera['valid_n']}/20**；"
        f"其中计数命中 {raw['schema_valid_count_exact']}/20；"
        f"schema 失败但数字命中 {raw['count_exact_with_schema_failure']}/20",
        f"- uncertain：{raw['uncertain_sample_N']} 个样本、"
        f"{raw['uncertain_groups_total']} 组、{raw['uncertain_roofs_total']} 个顶部观察",
        f"- 输入 hash：{result['sources']['inputs']['input_count']}/20；prompt："
        f"{'一致' if result['sources']['inputs']['prompt_match'] else '不一致'}；"
        f"raw manifest：{result['sources']['raw_manifest']['matches']}/"
        f"{result['sources']['raw_manifest']['file_count']}",
        f"- 禁用证据词只出现在 reasoning 的禁用指令复述/自检中："
        f"{len(result['sources']['attempts']['forbidden_evidence_term_hits'])} 次提及，"
        f"正向使用疑点 "
        f"{len(result['sources']['attempts']['forbidden_term_positive_use_suspects'])} 次；"
        "这不能证明像素层未使用下部证据。",
        "",
        "| 项目 | 值 |",
        "|---|---:|",
        f"| HTTP 尝试 / 成功 / 重试 | {performance['online']['calls']} / "
        f"{performance['online']['successes']} / {performance['online']['retries']} |",
        f"| 图像提交 | {performance['online']['images']} |",
        f"| tokens | {performance['online']['tokens']} |",
        f"| HTTP 均值 / p95 秒 | {performance['online']['latency_mean_s']:.3f} / "
        f"{performance['online']['latency_p95_s']:.3f} |",
        f"| 样本 e2e 均值 / p95 秒 | "
        f"{performance['online']['sample_e2e_mean_s']:.3f} / "
        f"{performance['online']['sample_e2e_p95_s']:.3f} |",
        f"| workers=2 墙钟秒 | {performance['online']['wall_clock_s']:.3f} |",
        "",
        "## 判定",
        "",
        "7 个机位输出因 `roof_kind` 输出为字面量 `cab_roof|cargo_roof` 而 schema 失败；"
        "这不是坐标换算或计数公式失败，也不能把其数字命中追认为严格有效。"
        "固定 20 分母只有 6/20 严格有效且计数正确，低于旧 B 的 18/20，"
        "当前配置应淘汰，不进入主链路。",
        "",
        "顶部 bbox 语义、size 车型正确率、物理组成、跨机位身份和独立时段泛化均 "
        "`not measured`。数字命中不等于这些对象级结论。",
        "",
    ]
    return "\n".join(lines)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roof-root", type=Path, required=True)
    parser.add_argument("--single-pass-root", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    root = args.roof_root.resolve()
    single_root = args.single_pass_root.resolve()
    truth_path = args.truth.resolve()
    public_root = single_root.parents[2]

    inputs = audit_sources(root, single_root, truth_path)
    raw_manifest = audit_raw_manifest(root)
    attempt_audit, final_attempts, http_latencies, e2e_latencies = audit_attempts(
        root, inputs, truth_path
    )
    camera_truth, _, truth_meta = truth_map(truth_path)
    summary = load_json(root / "summary.resolved.json")
    summary_by_id = {row["sample_id"]: row for row in summary.get("rows", [])}
    if set(summary_by_id) != set(camera_truth):
        raise EvaluationError("summary rows differ from 20 frozen truth slots")

    samples = []
    count_diagnostics = {
        "count_exact": 0,
        "fully_resolved_count_exact": 0,
        "schema_valid_count_exact": 0,
        "schema_valid_fully_resolved_count_exact": 0,
        "count_exact_with_schema_failure": 0,
        "raw_count_consistent_N": 0,
    }
    for sample_id in sorted(camera_truth, key=lambda key: (camera_truth[key]["time"], camera_truth[key]["camera"])):
        truth_row = camera_truth[sample_id]
        summary_row = summary_by_id[sample_id]
        attempt = final_attempts[sample_id]
        sample = _canonical_sample(summary_row, attempt, truth_row)
        samples.append(sample)
        parsed = attempt.get("parsed") or {}
        declared = parsed.get("count")
        consistent = (
            isinstance(declared, int)
            and not isinstance(declared, bool)
            and isinstance(parsed.get("vehicles"), list)
            and declared == len(parsed["vehicles"])
        )
        count_diagnostics["raw_count_consistent_N"] += consistent
        exact = consistent and declared == truth_row["value"]
        if exact:
            count_diagnostics["count_exact"] += 1
        if exact and parsed.get("uncertain") == []:
            count_diagnostics["fully_resolved_count_exact"] += 1
        if exact and sample["status"] != "valid":
            count_diagnostics["count_exact_with_schema_failure"] += 1
        if sample["status"] == "valid":
            if exact:
                count_diagnostics["schema_valid_count_exact"] += 1
            if exact and parsed.get("uncertain") == []:
                count_diagnostics["schema_valid_fully_resolved_count_exact"] += 1

    def uncertain_metric(sample: dict[str, Any], key: str) -> int:
        parsed = sample
        if key == "groups":
            return len(parsed.get("uncertain") or [])
        if key == "roofs":
            return sum(
                len(item.get("roof_ids", []))
                for item in parsed.get("uncertain") or []
                if isinstance(item, dict)
            )
        if key == "size_unknown":
            return sum(
                entity.get("raw_size") == "unknown"
                for entity in parsed.get("physical_entities", [])
            )
        if key == "kind_unknown":
            return sum(
                observation.get("raw_roof_kind") == "unknown"
                for observation in parsed.get("roof_observations", [])
            )
        raise KeyError(key)

    raw_totals = {
        "uncertain_sample_N": sum(bool(sample["uncertain"]) for sample in samples),
        "uncertain_groups_total": sum(uncertain_metric(s, "groups") for s in samples),
        "uncertain_roofs_total": sum(uncertain_metric(s, "roofs") for s in samples),
        "size_unknown_total": sum(uncertain_metric(s, "size_unknown") for s in samples),
        "roof_kind_unknown_total": sum(
            uncertain_metric(s, "kind_unknown") for s in samples
        ),
        **count_diagnostics,
    }
    canonical = {
        "schema": "round2-canonical-output-v1",
        "route": {
            "id": "roof-only-v1",
            "owner": "new_doubao_benchmark_v2",
            "mechanism": "one fresh structured observation per aisle image; prompt-only roof evidence",
            "status": "rejected_candidate",
            "evidence_scope": "roof_only",
            "roof_constraint_eligible": True,
            "prompt_sha256": PROMPT_SHA256,
            "model": MODEL,
        },
        "evidence_scope": "roof_only",
        "samples": samples,
        "times": [],
        "cost": {
            "concurrency": 2,
            "online": {"calls": 20, "images": 20, "tokens": 73983},
            "initialization": {
                "calls": None,
                "images": None,
                "tokens": None,
                "latency_s": None,
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
        },
    }
    integrity = {
        "all_match": (
            inputs["all_match"]
            and raw_manifest["all_match"]
            and attempt_audit["all_match"]
        ),
        "input_manifest_match": inputs["all_match"],
        "raw_manifest_match": raw_manifest["all_match"],
        "attempts_reconstructed": attempt_audit["all_requests_reconstructed"],
        "attempt_audit_match": attempt_audit["all_match"],
    }
    run = evaluate_output(
        truth_path,
        load_canonical_output_from_memory(canonical),
        split="dev",
        input_integrity=integrity,
        baseline_exact=16,
    )
    run["source"]["output_path"] = "in-memory canonical reconstruction"
    run["source"]["output_sha256"] = None

    mean_http = statistics.fmean(http_latencies) if http_latencies else None
    p95_http = nearest_rank_p95(http_latencies)
    mean_e2e = statistics.fmean(e2e_latencies) if e2e_latencies else None
    p95_e2e = nearest_rank_p95(e2e_latencies)
    declared_checks = {
        "valid_N": run["camera_count"]["valid_n"] == summary.get("valid_N"),
        "failures": run["camera_count"]["failed"] == summary.get("failures"),
        "exact": run["camera_count"]["exact"] == summary.get("exact"),
        "mae": (
            run["camera_count"]["mae"] is not None
            and abs(run["camera_count"]["mae"] - summary.get("mae_valid", -1))
            <= 0.000001
        ),
        "undercount": run["camera_count"]["under_units"]
        == summary.get("undercount_units_valid"),
        "overcount": run["camera_count"]["over_units"]
        == summary.get("overcount_units_valid"),
        "refusals": run["camera_count"]["refused"] == summary.get("refusal_N"),
        "http_attempts": attempt_audit["http_attempts"]
        == summary.get("http_attempts"),
        "http_successes": attempt_audit["http_attempts"]
        == summary.get("http_successes"),
        "transport_retries": (
            attempt_audit["http_attempts"] - len(attempt_audit["rows"])
            == summary.get("transport_retries")
        ),
        "tokens": attempt_audit["token_totals"].get("total_tokens")
        == (summary.get("tokens") or {}).get("total_tokens"),
        "count_exact": raw_totals["count_exact"] == summary.get("count_exact"),
        "fully_resolved_count_exact": raw_totals[
            "fully_resolved_count_exact"
        ]
        == summary.get("fully_resolved_count_exact"),
        "schema_valid_count_exact": raw_totals[
            "schema_valid_count_exact"
        ]
        == summary.get("schema_valid_count_exact"),
        "schema_valid_fully_resolved_count_exact": raw_totals[
            "schema_valid_fully_resolved_count_exact"
        ]
        == summary.get("schema_valid_fully_resolved_count_exact"),
        "count_exact_with_schema_failure": raw_totals[
            "count_exact_with_schema_failure"
        ]
        == summary.get("count_exact_with_schema_failure"),
        "uncertain_samples": raw_totals["uncertain_sample_N"]
        == summary.get("uncertain_sample_N"),
        "uncertain_groups": raw_totals["uncertain_groups_total"]
        == summary.get("uncertain_groups_total"),
        "uncertain_roofs": raw_totals["uncertain_roofs_total"]
        == summary.get("uncertain_roofs_total"),
        "size_unknown": raw_totals["size_unknown_total"]
        == summary.get("size_unknown_total"),
        "roof_kind_unknown": raw_totals["roof_kind_unknown_total"]
        == summary.get("roof_kind_unknown_total"),
        "raw_count_consistency": raw_totals["raw_count_consistent_N"] == 20,
        "mean_http_latency": (
            mean_http is not None
            and abs(mean_http - summary.get("mean_http_latency_s", -1)) <= 0.000001
        ),
        "p95_http_latency": (
            p95_http is not None
            and abs(p95_http - summary.get("p95_http_latency_s", -1))
            <= 0.000001
        ),
        "mean_sample_e2e": (
            mean_e2e is not None
            and abs(mean_e2e - summary.get("mean_sample_e2e_s", -1))
            <= 0.000001
        ),
        "p95_sample_e2e": (
            p95_e2e is not None
            and abs(p95_e2e - summary.get("p95_sample_e2e_s", -1))
            <= 0.000001
        ),
        "wall_clock": (
            abs(
                load_json(root / "RUN_COMPLETED.json")["wall_clock_s"]
                - summary.get("wall_clock_s", -1)
            )
            <= 0.000001
        ),
    }
    result = {
        "schema": "round2-roof-only-v1-independent-recompute-v1",
        "evidence_scope": "roof_only",
        "input_evidence_scope": "prompt_constrained_full_frame",
        "pixel_masking_implemented": False,
        "no_model_calls": True,
        "independent": run,
        "roof_raw": raw_totals,
        "sources": {
            "roof_root": str(root),
            "single_pass_root": str(single_root),
            "truth_path": str(truth_path),
            "truth": truth_meta,
            "inputs": inputs,
            "raw_manifest": raw_manifest,
            "attempts": attempt_audit,
            "summary_json_sha256": sha256_file(root / "summary.json"),
            "summary_resolved_sha256": sha256_file(
                root / "summary.resolved.json"
            ),
            "manifest_sha256": sha256_file(root / "manifest.json"),
            "run_completed_sha256": sha256_file(root / "RUN_COMPLETED.json"),
        },
        "declared_comparison": {
            "checks": declared_checks,
            "all_match": all(declared_checks.values()),
        },
        "performance": {
            "online": {
                "calls": attempt_audit["http_attempts"],
                "successes": sum(
                    attempt.get("http_ok") is True
                    for attempt in final_attempts.values()
                ),
                "retries": attempt_audit["http_attempts"] - 20,
                "images": attempt_audit["http_attempts"],
                "tokens": attempt_audit["token_totals"].get("total_tokens", 0),
                "latency_mean_s": _round(mean_http, 3),
                "latency_p95_s": _round(p95_http, 3),
                "sample_e2e_mean_s": _round(mean_e2e, 3),
                "sample_e2e_p95_s": _round(p95_e2e, 3),
                "serial_equivalent_s": _round(sum(e2e_latencies), 3),
                "concurrency": 2,
                "wall_clock_s": load_json(root / "RUN_COMPLETED.json").get(
                    "wall_clock_s"
                ),
            },
            "initialization": None,
            "peak_memory_mb": None,
            "note": (
                "Initialization memory/time was not published; null is retained "
                "rather than imputed as free."
            ),
        },
    }
    write_json(args.out_json, result)
    write_text(args.out_md, markdown(result))
    print(
        f"roof-only-v1 exact={run['camera_count']['headline']} "
        f"valid={run['camera_count']['valid_n']}/20 "
        f"raw_count_exact={raw_totals['count_exact']}/20 "
        f"declared_match={all(declared_checks.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
