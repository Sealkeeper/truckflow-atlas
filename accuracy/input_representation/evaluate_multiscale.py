"""Evaluate the frozen multiscale run without repairing failed answers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW = ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
DEFAULT_BASELINE = ROOT / "accuracy" / "reviewed" / "evaluation-clean-v1.json"
DEFAULT_RUN = ROOT / "accuracy" / "runs" / "multiscale_v1"
DEFAULT_JSON = DEFAULT_RUN / "summary.json"
DEFAULT_EVIDENCE = ROOT / "accuracy" / "evidence" / "input_representation" / "errors_contact.jpg"
FRAMES = ROOT / "assets" / "frames"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def load_truth(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "truckflow-final-review-v2" or not payload.get("complete"):
        raise SystemExit("review truth is not complete truckflow-final-review-v2")
    result: dict[str, int] = {}
    for row in payload["samples"]:
        if not row.get("completed"):
            continue
        for camera in ("north", "south"):
            value = (row.get("camera_counts") or {}).get(camera)
            if isinstance(value, int):
                sample_id = f"{camera}_{int(row['time'])}"
                if sample_id in result:
                    raise SystemExit(f"duplicate truth sample: {sample_id}")
                result[sample_id] = value
    return result


def font(size: int, bold: bool = False):
    path = Path("C:/Windows/Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc")
    return ImageFont.truetype(str(path), size)


def draw_evidence(rows: list[dict[str, Any]], out: Path) -> None:
    panel_w, panel_h = 480, 360
    cols, rows_count = 4, 5
    label_h = 66
    canvas = Image.new(
        "RGB", (panel_w * cols, 68 + (panel_h + label_h) * rows_count), "white"
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (18, 12),
        "多尺度 v1 · 原帧上的模型框与官方计数状态",
        font=font(27, True),
        fill=(25, 32, 40),
    )
    draw.text(
        (20, 44),
        "绿=有效且 exact；红=有效但计数错误；橙=失败（框仅作诊断，不计正确）",
        font=font(16),
        fill=(80, 85, 92),
    )

    for index, row in enumerate(rows):
        col, grid_row = index % cols, index // cols
        x, y = col * panel_w, 68 + grid_row * (panel_h + label_h)
        image = Image.open(FRAMES / f"{row['sample_id']}.jpg").convert("RGB")
        image.thumbnail((panel_w, panel_h), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (panel_w, panel_h), "white")
        offset_x = (panel_w - image.width) // 2
        offset_y = (panel_h - image.height) // 2
        panel.paste(image, (offset_x, offset_y))
        pd = ImageDraw.Draw(panel)
        if row["status"] == "ok":
            color = (24, 150, 72) if row["error"] == 0 else (205, 45, 55)
        else:
            color = (230, 132, 20)
        for vehicle in row.get("diagnostic_boxes") or []:
            bbox = vehicle.get("bbox_full_normalized")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            box = (
                offset_x + float(x0) * image.width,
                offset_y + float(y0) * image.height,
                offset_x + float(x1) * image.width,
                offset_y + float(y1) * image.height,
            )
            pd.rectangle(box, outline=color, width=4)
            label = str(vehicle.get("id") or "")
            if label:
                pd.rectangle(
                    (box[0], box[1], box[0] + max(30, 13 * len(label)), box[1] + 22),
                    fill=color,
                )
                pd.text((box[0] + 3, box[1] + 2), label, font=font(16, True), fill="white")
        canvas.paste(panel, (x, y))
        status = row["status"]
        predicted = "—" if row["predicted"] is None else str(row["predicted"])
        details = (
            f"{row['sample_id']}  gold={row['gold']} pred={predicted} "
            f"status={status}"
        )
        draw.text((x + 5, y + panel_h + 4), details, font=font(17, True), fill=(25, 32, 40))
        reason = (
            row.get("failure_reason")
            if status != "ok"
            else f"error={row['error']:+d}"
        )
        draw.text(
            (x + 5, y + panel_h + 29),
            str(reason)[:62],
            font=font(13),
            fill=(90, 55, 30) if status != "ok" else (70, 75, 82),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=93)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    truth = load_truth(args.review)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    baseline_rows = {row["sample_id"]: row for row in baseline["rows"]}
    if set(truth) != set(baseline_rows):
        raise SystemExit("truth and baseline sample sets differ")
    if len(truth) != 20 or baseline["metrics"]["exact"] != 16:
        raise SystemExit("unexpected truth/baseline contract")

    run_meta_path = args.run_dir / "_run.json"
    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    expected_files = {f"{sample_id}.json" for sample_id in truth}
    sample_files = sorted(
        path for path in args.run_dir.glob("*.json") if path.name in expected_files
    )
    if len(sample_files) != 20:
        raise SystemExit(f"expected 20 sample files, found {len(sample_files)}")
    run_files: dict[str, dict[str, Any]] = {}
    for path in sample_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = payload.get("sample_id")
        if sample_id not in truth:
            raise SystemExit(f"{path.name}: unknown sample_id {sample_id!r}")
        if sample_id in run_files:
            raise SystemExit(f"duplicate sample_id {sample_id}")
        run_files[sample_id] = payload
    if set(run_files) != set(truth):
        raise SystemExit("run sample set differs from truth")

    rows: list[dict[str, Any]] = []
    for sample_id, gold in sorted(truth.items()):
        payload = run_files[sample_id]
        baseline_row = baseline_rows[sample_id]
        parsed_counts = (payload.get("parsed") or {}).get("counts") or {}
        diagnostic_total = parsed_counts.get("total")
        official_ok = payload.get("status") == "ok" and isinstance(diagnostic_total, int)
        predicted = diagnostic_total if official_ok else None
        error = predicted - gold if predicted is not None else None
        baseline_correct = baseline_row["error"] == 0
        if official_ok and baseline_correct and error == 0:
            outcome = "baseline_correct_retained"
        elif official_ok and baseline_correct:
            outcome = "regression"
        elif official_ok and error == 0:
            outcome = "historical_error_fixed"
        elif official_ok:
            outcome = "historical_error_still_wrong"
        elif baseline_correct:
            outcome = "baseline_correct_but_failed"
        else:
            outcome = "historical_error_but_failed"
        rows.append(
            {
                "sample_id": sample_id,
                "camera": baseline_row["camera"],
                "time_s": baseline_row["time_s"],
                "gold": gold,
                "baseline_predicted": baseline_row["predicted"],
                "baseline_error": baseline_row["error"],
                "baseline_correct": baseline_correct,
                "status": "ok" if official_ok else "failed",
                "failure_kind": payload.get("failure_kind"),
                "failure_reason": payload.get("failure_reason"),
                "predicted": predicted,
                "error": error,
                "diagnostic_raw_total": diagnostic_total,
                "diagnostic_raw_error_if_ignored": (
                    diagnostic_total - gold if isinstance(diagnostic_total, int) else None
                ),
                "outcome": outcome,
                "wall_latency_s": payload.get("wall_latency_s"),
                "attempts": len(payload.get("attempts") or []),
                "transport_retry_count": payload.get("transport_retry_count"),
                "usage": payload.get("usage"),
                "validation_errors": payload.get("validation_errors") or [],
                "output_audit": payload.get("output_audit"),
                "diagnostic_boxes": payload.get("raw_bbox_audit") or [],
                "file": f"{sample_id}.json",
                "sha256": sha256_file(args.run_dir / f"{sample_id}.json"),
            }
        )

    graded = [row for row in rows if row["status"] == "ok"]
    failures = [row for row in rows if row["status"] != "ok"]
    exact = sum(row["error"] == 0 for row in graded)
    mae = sum(abs(row["error"]) for row in graded) / len(graded) if graded else None
    diagnostic_exact = sum(row["diagnostic_raw_error_if_ignored"] == 0 for row in rows)

    sample_wall = [float(row["wall_latency_s"]) for row in rows]
    run_files_payload = [run_files[sample_id] for sample_id in truth]
    usages = [payload.get("usage") or {} for payload in run_files_payload]
    prompt_tokens = sum(int(usage.get("prompt_tokens") or 0) for usage in usages)
    completion_tokens = sum(int(usage.get("completion_tokens") or 0) for usage in usages)
    total_tokens = sum(int(usage.get("total_tokens") or 0) for usage in usages)
    reasoning_tokens = sum(
        int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        for usage in usages
    )
    attempts = [attempt for payload in run_files_payload for attempt in payload.get("attempts") or []]
    attempt_latencies = [float(attempt["latency_s"]) for attempt in attempts if "latency_s" in attempt]
    transport_retries = sum(int(payload.get("transport_retry_count") or 0) for payload in run_files_payload)

    baseline_usage = []
    baseline_wall = []
    for path in sorted((ROOT / "accuracy" / "runs" / "aisle_clean").glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = (payload.get("runs") or [{}])[0]
        if run.get("ok"):
            baseline_usage.append(run.get("usage") or {})
            baseline_wall.append(float(run.get("latency_s") or 0))
    baseline_prompt_tokens = sum(int(usage.get("prompt_tokens") or 0) for usage in baseline_usage)
    baseline_completion_tokens = sum(
        int(usage.get("completion_tokens") or 0) for usage in baseline_usage
    )
    baseline_total_tokens = sum(int(usage.get("total_tokens") or 0) for usage in baseline_usage)

    seen_totals = {"global": 0, "detail": 0, "both": 0}
    duplicate_candidates = []
    for row in graded:
        audit = row.get("output_audit") or {}
        for key in seen_totals:
            seen_totals[key] += int((audit.get("seen_in_counts") or {}).get(key) or 0)
        for candidate in audit.get("bbox_duplicate_candidates_iou_ge_0_85") or []:
            duplicate_candidates.append(
                {
                    "sample_id": row["sample_id"],
                    **candidate,
                }
            )

    outcome_counts = {
        key: sum(row["outcome"] == key for row in rows)
        for key in (
            "baseline_correct_retained",
            "regression",
            "historical_error_fixed",
            "historical_error_still_wrong",
            "baseline_correct_but_failed",
            "historical_error_but_failed",
        )
    }
    run_set_text = "\n".join(
        f"{row['sample_id']}:{row['sha256']}" for row in rows
    )

    summary = {
        "schema": "truckflow-multiscale-evaluation-v1",
        "route": "input-representation/single-call-multiscale-v1",
        "truth": {
            "file": relative(args.review),
            "sha256": sha256_file(args.review),
            "n": len(truth),
            "denominator_includes_failures": True,
        },
        "baseline": {
            "file": relative(args.baseline),
            "sha256": sha256_file(args.baseline),
            "exact": baseline["metrics"]["exact"],
            "n": baseline["metrics"]["n_total"],
            "mae_graded": baseline["metrics"]["mae_graded"],
            "failed": baseline["metrics"]["failed"],
            "missing": baseline["metrics"]["missing"],
        },
        "run": {
            "directory": relative(args.run_dir),
            "meta_file": relative(run_meta_path),
            "meta_sha256": sha256_file(run_meta_path),
            "status": run_meta["status"],
            "model_id": run_meta["model_id"],
            "prompt_sha256": run_meta["prompt_sha256"],
            "manifest_sha256": run_meta["manifest_sha256"],
            "preregistration_sha256": run_meta["preregistration_sha256"],
            "raw_files": len(rows),
            "run_set_sha256": hashlib.sha256(run_set_text.encode("utf-8")).hexdigest(),
        },
        "metrics": {
            "n_total": 20,
            "graded": len(graded),
            "exact": exact,
            "exact_rate_graded": round(exact / len(graded) * 100, 1) if graded else None,
            "exact_rate_all": round(exact / 20 * 100, 1),
            "mae_graded": round(mae, 3) if mae is not None else None,
            "mae_denominator_graded": len(graded),
            "under": sum(max(0, -row["error"]) for row in graded),
            "over": sum(max(0, row["error"]) for row in graded),
            "failed": len(failures),
            "missing": 0,
            "transport_retries": transport_retries,
            "diagnostic_exact_if_schema_failures_were_ignored": diagnostic_exact,
            "diagnostic_note": (
                "This is not the official score. Failed outputs remain failures under "
                "the frozen contract; the diagnostic count only quantifies schema usability."
            ),
        },
        "outcomes": {
            **outcome_counts,
            "historical_errors": 4,
            "baseline_correct_frames": 16,
        },
        "historical_error_rows": [
            {
                key: row[key]
                for key in (
                    "sample_id",
                    "gold",
                    "baseline_predicted",
                    "status",
                    "predicted",
                    "diagnostic_raw_total",
                    "failure_kind",
                    "outcome",
                )
            }
            for row in rows
            if not row["baseline_correct"]
        ],
        "regression_rows": [
            {
                key: row[key]
                for key in (
                    "sample_id",
                    "gold",
                    "baseline_predicted",
                    "status",
                    "predicted",
                    "diagnostic_raw_total",
                    "failure_kind",
                    "outcome",
                )
            }
            for row in rows
            if row["outcome"] in {"regression", "baseline_correct_but_failed"}
        ],
        "failure_breakdown": {
            kind: sum(row["failure_kind"] == kind for row in failures)
            for kind in sorted({row["failure_kind"] for row in failures if row["failure_kind"]})
        },
        "vehicle_output_audit": {
            "note": "Only successful schema-valid outputs. No full per-vehicle truth is available.",
            "graded_vehicle_count": sum(
                int((row.get("output_audit") or {}).get("vehicle_count") or 0)
                for row in graded
            ),
            "unique_id_failures": sum(
                any("unique" in error for error in row["validation_errors"]) for row in graded
            ),
            "seen_in": seen_totals,
            "high_iou_duplicate_candidates": duplicate_candidates,
        },
        "cost": {
            "primary_requests": run_meta["primary_requests"],
            "total_http_attempts": len(attempts),
            "transport_retries": transport_retries,
            "images_per_primary_request": 2,
            "image_inputs": run_meta["primary_requests"] * 2,
            "pixels_per_request": 2624000,
            "total_pixels": run_meta["primary_requests"] * 2624000,
            "baseline_pixels_per_request": 1996800,
            "pixel_increase_vs_baseline_pct": 31.41,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "prompt_tokens_per_sample": round(prompt_tokens / 20, 1),
            "baseline_prompt_tokens": baseline_prompt_tokens,
            "baseline_completion_tokens": baseline_completion_tokens,
            "baseline_total_tokens": baseline_total_tokens,
            "prompt_token_increase_vs_baseline_pct": (
                round((prompt_tokens / baseline_prompt_tokens - 1) * 100, 1)
                if baseline_prompt_tokens
                else None
            ),
            "attempt_latency_mean_s": round(statistics.mean(attempt_latencies), 3),
            "attempt_latency_p95_s": nearest_rank_p95(attempt_latencies),
            "baseline_attempt_latency_mean_s": (
                round(statistics.mean(baseline_wall), 3) if baseline_wall else None
            ),
            "baseline_attempt_latency_p95_s": nearest_rank_p95(baseline_wall),
            "sample_wall_mean_s": round(statistics.mean(sample_wall), 3),
            "sample_wall_p95_s": nearest_rank_p95(sample_wall),
            "total_wall_s": run_meta["total_wall_latency_s"],
            "concurrency": 1,
        },
        "rows": rows,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    draw_evidence(rows, args.evidence)

    metrics = summary["metrics"]
    print(
        f"N={metrics['n_total']} graded={metrics['graded']} "
        f"exact={metrics['exact']}/{metrics['graded']} "
        f"exact_all={metrics['exact_rate_all']}% MAE={metrics['mae_graded']} "
        f"failed={metrics['failed']} missing={metrics['missing']}"
    )
    print(
        f"diagnostic_schema_ignored_exact="
        f"{metrics['diagnostic_exact_if_schema_failures_were_ignored']}/20"
    )
    print(
        f"requests={summary['cost']['primary_requests']} images={summary['cost']['image_inputs']} "
        f"tokens={summary['cost']['total_tokens']} "
        f"p95={summary['cost']['sample_wall_p95_s']}s "
        f"wall={summary['cost']['total_wall_s']}s"
    )
    print(f"wrote {args.json_out}")
    print(f"evidence {args.evidence}")


if __name__ == "__main__":
    main()
