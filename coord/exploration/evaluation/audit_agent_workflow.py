"""Audit route summaries for leakage, count carry-over, and dropped failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from compare_routes import load_summary, number, pick


def audit(summary: dict[str, Any]) -> dict[str, Any]:
    workflow = summary.get("workflow_audit") or {}
    camera = summary.get("camera_count") or {}
    findings: list[dict[str, str]] = []
    hard_failures = 0
    untested = 0

    def add(level: str, check: str, detail: str) -> None:
        nonlocal hard_failures, untested
        findings.append({"level": level, "check": check, "detail": detail})
        if level == "FAIL":
            hard_failures += 1
        elif level == "未测":
            untested += 1

    leakage_fields = (
        ("human_boxes_used_as_model_input", "人工红框是否进入模型输入"),
        ("same_frame_annotations_exposed", "同帧人工标注是否进入检索上下文"),
        ("future_frames_exposed", "是否使用未来帧/未来观察"),
    )
    for key, label in leakage_fields:
        value = workflow.get(key)
        if value is None:
            add("未测", key, f"{label}：字段缺失")
        elif value is True:
            add("FAIL", key, f"{label}：是")
        else:
            add("PASS", key, f"{label}：否")

    scope = pick(workflow, "memory_retrieval_scope", "annotation_scope")
    if scope is None:
        add("未测", "memory_retrieval_scope", "检索/标注时间范围字段缺失")
    elif any(
        token in str(scope).lower()
        for token in ("future", "test_frame", "same_frame")
    ):
        add("FAIL", "memory_retrieval_scope", f"检索范围={scope}")
    else:
        add("PASS", "memory_retrieval_scope", f"检索范围={scope}")

    carryover = workflow.get("previous_count_carryover")
    new_evidence = workflow.get("carryover_has_new_evidence")
    if carryover is None:
        add("未测", "previous_count_carryover", "是否续填上一帧数量：字段缺失")
    elif carryover is False:
        add("PASS", "previous_count_carryover", "没有仅按上一帧数量续填")
    elif new_evidence is True:
        add("WARN", "previous_count_carryover", "有续填，但登记了新增图像证据")
    else:
        add("FAIL", "previous_count_carryover", "仅续填上一帧数量，没有新增图像证据")

    skipped = workflow.get("failures_skipped")
    if skipped is None:
        add("未测", "failures_skipped", "失败是否跳过：字段缺失")
    elif skipped is True:
        add("FAIL", "failures_skipped", "调用失败被跳过")
    else:
        add("PASS", "failures_skipped", "失败未被跳过")

    counted = workflow.get("failure_counted_in_denominator")
    if counted is None:
        add("未测", "failure_counted_in_denominator", "失败分母字段缺失")
    elif counted is False:
        add("FAIL", "failure_counted_in_denominator", "失败未保留在固定分母")
    else:
        add("PASS", "failure_counted_in_denominator", "失败保留在固定分母")

    n_total = pick(camera, "n_total", "N")
    valid = pick(camera, "valid_n", "graded")
    failed = pick(camera, "failed", "failures")
    missing = pick(camera, "missing")
    if (
        n_total is not None
        and valid is not None
        and failed is not None
        and missing is not None
        and int(valid) + int(failed) + int(missing) != int(n_total)
    ):
        add(
            "FAIL",
            "fixed_denominator",
            f"valid+failed+missing={valid}+{failed}+{missing} != N={n_total}",
        )
    elif n_total is None or valid is None or failed is None or missing is None:
        add("未测", "fixed_denominator", "N/valid/failed/missing 未完整发布")
    else:
        add(
            "PASS",
            "fixed_denominator",
            f"N={n_total}, valid={valid}, failed={failed}, missing={missing}",
        )

    return {
        "route_id": (summary.get("route") or {}).get("id"),
        "source": summary["_source"],
        "findings": findings,
        "hard_failures": hard_failures,
        "untested": untested,
        "verdict": "FAIL" if hard_failures else ("未测" if untested else "PASS"),
    }


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Agent workflow audit",
        "",
        "| Route | Verdict | Hard failures | Untested | Findings |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        level_counts = {}
        for item in row["findings"]:
            level_counts[item["level"]] = level_counts.get(item["level"], 0) + 1
        findings = "; ".join(
            f"{item['level']} {item['check']}: {item['detail']}"
            for item in row["findings"]
        )
        lines.append(
            f"| {row['route_id']} | {row['verdict']} | {number(row['hard_failures'])} "
            f"| {number(row['untested'])} | {findings} |"
        )
    lines += [
        "",
        "Hard failures include human red boxes or future frames in the retrieval context, "
        "count carry-over without new evidence, skipped API failures, or a broken fixed denominator.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", nargs="+", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()

    summaries = [load_summary(path) for path in args.summary]
    rows = [audit(summary) for summary in summaries]
    report = {
        "schema": "truckflow-agent-workflow-audit-v1",
        "rows": rows,
    }
    text = markdown(rows)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(text, encoding="utf-8")
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(text, end="")
    raise SystemExit(1 if any(row["hard_failures"] for row in rows) else 0)


if __name__ == "__main__":
    main()
