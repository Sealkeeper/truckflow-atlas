"""Compare explicitly supplied route summaries.

This tool never scans a session directory. Every input is named on the command
line. Missing metrics are rendered as "未测"; failures stay in the published
denominator and are shown separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA = "truckflow-route-summary-v1"


def pick(obj: dict[str, Any] | None, *names: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]
    return default


def number(value: Any) -> str:
    if value is None:
        return "未测"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def percent(value: Any) -> str:
    if value is None:
        return "未测"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def load_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: expected schema {SCHEMA!r}")
    route = payload.get("route") or {}
    route_id = route.get("id")
    if not route_id:
        raise SystemExit(f"{path}: route.id is required")
    payload["_source"] = path.as_posix()
    return payload


def metric_columns(
    block: dict[str, Any] | None,
    default_n: int | None,
    label: str,
) -> dict[str, Any]:
    block = block or {}
    n_total = pick(block, "n_total", "N", default=default_n)
    valid_n = pick(block, "valid_n", "graded")
    failed = pick(block, "failed", "failures")
    missing = pick(block, "missing")
    exact = pick(block, "exact", "exact_count")
    mae = pick(block, "mae", "mae_graded")
    warnings: list[str] = []
    status = str(block.get("status") or "").lower()
    unmeasured = (
        status in {"not measured", "unmeasured"}
        and valid_n is None
        and failed is None
        and missing is None
        and exact is None
        and mae is None
    )

    if (
        valid_n is None
        and n_total is not None
        and failed is not None
        and missing is not None
    ):
        valid_n = int(n_total) - int(failed) - int(missing)

    if n_total is None:
        warnings.append(f"data {label}: N 未发布")
    if not unmeasured and (failed is None or missing is None):
        warnings.append(f"data {label}: failed/missing 未发布")
    if (
        not unmeasured
        and n_total is not None
        and valid_n is not None
        and failed is not None
        and missing is not None
        and int(valid_n) + int(failed) + int(missing) != int(n_total)
    ):
        warnings.append(
            f"data {label}: valid+failed+missing != N "
            f"({valid_n}+{failed}+{missing} != {n_total})"
        )
    if exact is not None and valid_n is not None and int(exact) > int(valid_n):
        warnings.append(f"data {label}: exact > valid_N")

    if exact is None or valid_n is None or n_total is None:
        exact_display = "未测"
    else:
        exact_display = (
            f"{exact}/{valid_n} (N={n_total}; "
            f"fail={number(failed)}; miss={number(missing)})"
        )
    if mae is None:
        mae_display = "未测"
    else:
        mae_display = f"{number(mae)} (n={number(valid_n)})"

    return {
        "n_total": n_total,
        "valid_n": valid_n,
        "failed": failed,
        "missing": missing,
        "exact": exact,
        "mae": mae,
        "exact_display": exact_display,
        "mae_display": mae_display,
        "warnings": warnings,
    }


def release_columns(summary: dict[str, Any]) -> dict[str, Any]:
    release = summary.get("release") or {}
    review = summary.get("review") or {}
    n_total = pick(release, "n_total", default=pick(summary.get("camera_count"), "n_total"))
    auto = pick(release, "auto_released", "auto_release_count")
    correct = pick(release, "correct", "correct_count")
    errors = pick(release, "errors", "error_count")
    if auto is None and correct is not None and errors is not None:
        auto = int(correct) + int(errors)
    coverage = pick(release, "coverage", "auto_release_coverage")
    if coverage is None and auto is not None and n_total:
        coverage = float(auto) / float(n_total)
    error_rate = pick(release, "error_rate")
    if error_rate is None and errors is not None and auto:
        error_rate = float(errors) / float(auto)

    reviewed = pick(review, "reviewed", "review_count")
    review_rate = pick(review, "review_rate")
    if review_rate is None and reviewed is not None and n_total:
        review_rate = float(reviewed) / float(n_total)

    if auto is None and correct is None and errors is None:
        release_display = "未测"
    elif auto is None:
        release_display = "未测"
    else:
        release_display = (
            f"correct={number(correct)}; errors={number(errors)}; "
            f"cov={percent(coverage)}; err_rate={percent(error_rate)}"
        )
    if review_rate is None and reviewed is None:
        review_display = "未测"
    else:
        review_display = (
            f"{number(reviewed)}/{number(n_total)} ({percent(review_rate)})"
            if reviewed is not None
            else percent(review_rate)
        )
    return {
        "release_display": release_display,
        "review_display": review_display,
        "coverage": coverage,
        "error_rate": error_rate,
        "review_rate": review_rate,
    }


def cost_columns(summary: dict[str, Any]) -> dict[str, Any]:
    cost = summary.get("cost") or {}
    latency = cost.get("latency_s")
    if isinstance(latency, dict):
        mean = pick(latency, "mean", "avg")
        p95 = pick(latency, "p95")
    else:
        mean = pick(cost, "latency_s_mean", "latency_mean_s")
        p95 = pick(cost, "latency_s_p95", "latency_p95_s")
    return {
        "calls": pick(cost, "calls", "calls_total"),
        "images": pick(cost, "images", "images_total"),
        "tokens": pick(cost, "tokens_total", "total_tokens"),
        "latency_mean": mean,
        "latency_p95": p95,
    }


def workflow_warnings(summary: dict[str, Any]) -> list[str]:
    audit = summary.get("workflow_audit") or {}
    if not audit:
        return ["workflow: 未测"]
    issues: list[str] = []
    checks = (
        ("human_boxes_used_as_model_input", True, "FAIL 人工红框进入模型输入"),
        ("same_frame_annotations_exposed", True, "FAIL 同帧人工标注进入检索上下文"),
        ("future_frames_exposed", True, "FAIL 使用了未来帧信息"),
        ("failures_skipped", True, "FAIL 调用失败被跳过"),
        ("failure_counted_in_denominator", False, "FAIL 失败未计入固定分母"),
    )
    for key, bad_value, message in checks:
        value = audit.get(key)
        if value is None:
            issues.append(f"workflow {key}=未测")
        elif value == bad_value:
            issues.append(f"workflow {message}")

    scope = pick(audit, "memory_retrieval_scope", "annotation_scope")
    if scope is None:
        issues.append("workflow memory_retrieval_scope=未测")
    elif any(
        token in str(scope).lower()
        for token in ("future", "test_frame", "same_frame")
    ):
        issues.append(f"workflow FAIL 检索范围={scope}")

    carryover = audit.get("previous_count_carryover")
    new_evidence = audit.get("carryover_has_new_evidence")
    if carryover is None:
        issues.append("workflow previous_count_carryover=未测")
    elif carryover and new_evidence is not True:
        issues.append("workflow WARN 仅续填上一帧数量，无新增图像证据")

    if not issues:
        return ["workflow OK"]
    return issues


def row_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    route = summary["route"]
    camera = metric_columns(
        summary.get("camera_count"),
        default_n=summary.get("dataset", {}).get("n_camera_samples"),
        label="count",
    )
    unique = metric_columns(
        summary.get("unique"),
        default_n=summary.get("dataset", {}).get("n_times"),
        label="unique",
    )
    overlap = metric_columns(
        summary.get("overlap"),
        default_n=summary.get("dataset", {}).get("n_times"),
        label="overlap",
    )
    release = release_columns(summary)
    cost = cost_columns(summary)
    identity = summary.get("identity") or {}
    identity_status = pick(identity, "status", default="未测")
    identity_exact = pick(identity, "exact")
    identity_display = (
        "未测"
        if identity_exact is None
        else f"{identity_exact}/{pick(identity, 'n_total', default='?')}"
    )
    warnings = (
        camera["warnings"]
        + unique["warnings"]
        + overlap["warnings"]
        + workflow_warnings(summary)
    )
    return {
        "route_id": route.get("id"),
        "owner": route.get("owner"),
        "mechanism": route.get("mechanism"),
        "branch": route.get("branch"),
        "commit": route.get("commit"),
        "status": route.get("status"),
        "dataset_split": summary.get("dataset", {}).get("split"),
        "camera_count": camera,
        "unique": unique,
        "overlap": overlap,
        "release": release,
        "review_display": release["review_display"],
        "cost": cost,
        "identity_display": identity_display,
        "identity_status": identity_status,
        "warnings": warnings,
        "source": summary["_source"],
    }


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Route comparison",
        "",
        "Count exact is total truck-count exactness only; it is not vehicle-ID or model-class accuracy.",
        "A missing field is `未测`; failures remain visible against the fixed N.",
        "",
        "| Route | Split | Count exact | Count MAE | Unique exact | Unique MAE | Overlap exact | Overlap MAE | Vehicle ID |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {route} | {split} | {ce} | {cm} | {ue} | {um} | {oe} | {om} | {identity} |".format(
                route=row["route_id"],
                split=row["dataset_split"] or "未测",
                ce=row["camera_count"]["exact_display"],
                cm=row["camera_count"]["mae_display"],
                ue=row["unique"]["exact_display"],
                um=row["unique"]["mae_display"],
                oe=row["overlap"]["exact_display"],
                om=row["overlap"]["mae_display"],
                identity=row["identity_display"],
            )
        )
    lines += [
        "",
        "| Route | Auto release | Review | Calls | Images | Tokens | Latency mean/p95 | Audit / data notes |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        cost = row["cost"]
        latency = (
            f"{number(cost['latency_mean'])} / {number(cost['latency_p95'])} s"
            if cost["latency_mean"] is not None or cost["latency_p95"] is not None
            else "未测"
        )
        lines.append(
            "| {route} | {release} | {review} | {calls} | {images} | {tokens} | {latency} | {workflow} |".format(
                route=row["route_id"],
                release=row["release"]["release_display"],
                review=row["review_display"],
                calls=number(cost["calls"]),
                images=number(cost["images"]),
                tokens=number(cost["tokens"]),
                latency=latency,
                workflow="; ".join(row["warnings"]) or "OK",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", nargs="+", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()

    summaries = [load_summary(path) for path in args.summary]
    rows = [row_from_summary(summary) for summary in summaries]
    report = {
        "schema": "truckflow-route-comparison-v1",
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


if __name__ == "__main__":
    main()
