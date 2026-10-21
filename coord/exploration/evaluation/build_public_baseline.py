"""Build the public clean-aisle manifest, metrics, and raw file list.

The 20 files are fixed. This script verifies file hashes, truth hashes,
per-sample predictions, and rejects a run directory containing extra or
non-aisle sample files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any


ROUTE = {
    "id": "clean-aisle-doubao-v1",
    "owner": "clean_eval",
    "mechanism": "fixed aisle crop, one Doubao vision call per camera sample",
    "branch": "accuracy/clean-baseline",
    "commit": "f5eb47614494c4a8e4b8df6d5bcd426ac61207ec",
    "status": "baseline",
    "pr": "https://github.com/Sealkeeper/truckflow-atlas/pull/9",
}

VIEW_CONTRACT = (
    "exactly one <camera>_<seconds>_aisle.json per sample; "
    "grid_aisle, grid_grid_aisle and every other view are rejected"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_samples(evaluation: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    rows = evaluation.get("rows") or []
    if len(rows) != 20:
        raise SystemExit(f"expected 20 evaluation rows, found {len(rows)}")

    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sample_id = row["sample_id"]
        if sample_id in seen:
            raise SystemExit(f"duplicate sample_id: {sample_id}")
        seen.add(sample_id)

        path = root / row["file"]
        if not path.is_file():
            raise SystemExit(f"missing run file: {path}")
        actual_sha = sha256_file(path)
        if actual_sha != row["sha256"]:
            raise SystemExit(
                f"{sample_id}: sha256 mismatch {actual_sha} != {row['sha256']}"
            )

        run = load_json(path)
        runs = run.get("runs") or []
        if len(runs) != 1 or not runs[0].get("ok"):
            raise SystemExit(f"{sample_id}: expected exactly one successful run")
        result = runs[0]
        parsed_total = (result.get("parsed") or {}).get("counts", {}).get("total")
        if parsed_total != row["predicted"]:
            raise SystemExit(
                f"{sample_id}: parsed total {parsed_total} != evaluation "
                f"prediction {row['predicted']}"
            )

        samples.append(
            {
                "sample_id": sample_id,
                "camera": row["camera"],
                "time_s": row["time_s"],
                "view": "aisle",
                "path": row["file"],
                "sha256": actual_sha,
                "bytes": path.stat().st_size,
                "truth_count": row["gold"],
                "predicted_count": row["predicted"],
                "error": row["error"],
                "status": row["status"],
                "attempts": row["attempts"],
                "model": row["model"],
                "model_id": result.get("model_id"),
                "result_total": parsed_total,
                "latency_s": result.get("latency_s"),
                "total_tokens": (result.get("usage") or {}).get("total_tokens"),
            }
        )
    return samples


def assert_directory_contract(run_dir: Path, sample_files: set[str]) -> dict[str, Any]:
    json_files = sorted(path.name for path in run_dir.glob("*.json"))
    sample_json = {name for name in json_files if not name.startswith("_")}
    extra = sorted(sample_json - sample_files)
    missing = sorted(sample_files - sample_json)
    non_aisle = sorted(name for name in sample_json if not name.endswith("_aisle.json"))
    if extra or missing or non_aisle:
        raise SystemExit(
            f"run directory contract failed: extra={extra}, "
            f"missing={missing}, non_aisle={non_aisle}"
        )
    return {
        "json_files_total": len(json_files),
        "sample_files": len(sample_json),
        "underscore_metadata_files": sorted(
            name for name in json_files if name.startswith("_")
        ),
        "extra_sample_files": extra,
        "missing_sample_files": missing,
        "non_aisle_sample_files": non_aisle,
        "rejected_views": ["grid_aisle", "grid_grid_aisle"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--evaluation",
        type=Path,
        default=Path("accuracy/reviewed/evaluation-clean-v1.json"),
    )
    parser.add_argument("--run-dir", type=Path, default=Path("accuracy/runs/aisle_clean"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args()

    root = args.root.resolve()
    evaluation_path = (root / args.evaluation).resolve()
    run_dir = (root / args.run_dir).resolve()
    out_dir = args.out_dir.resolve()

    evaluation = load_json(evaluation_path)
    metrics = evaluation["metrics"]
    if metrics["n_total"] != 20 or metrics["graded"] != 20:
        raise SystemExit(f"unexpected baseline denominator: {metrics}")
    if metrics["exact"] != 16 or metrics["failed"] != 0 or metrics["missing"] != 0:
        raise SystemExit(f"unexpected baseline metrics: {metrics}")

    truth_path = root / evaluation["review"]["file"]
    truth_sha = sha256_file(truth_path)
    if truth_sha != evaluation["review"]["sha256"]:
        raise SystemExit(
            f"truth sha256 mismatch {truth_sha} != {evaluation['review']['sha256']}"
        )

    samples = build_samples(evaluation, root)
    directory = assert_directory_contract(
        run_dir, {Path(row["path"]).name for row in samples}
    )
    evaluation_sha = sha256_file(evaluation_path)

    manifest = {
        "schema": "truckflow-clean-baseline-manifest-v1",
        "published_on": args.today,
        "route": ROUTE,
        "dataset": {
            "name": "user-final-review-v2-2026-10-21",
            "split": "dev",
            "n_camera_samples": 20,
            "n_times": 10,
            "truth_file": evaluation["review"]["file"],
            "truth_sha256": truth_sha,
            "note": (
                "All 20 camera frames were inspected during development. "
                "This is a regression baseline, not a blind result."
            ),
        },
        "view_contract": VIEW_CONTRACT,
        "run_directory": args.run_dir.as_posix(),
        "run_set_sha256": evaluation["runs"]["run_set_sha256"],
        "evaluation_file": args.evaluation.as_posix(),
        "evaluation_sha256": evaluation_sha,
        "directory_check": directory,
        "fixed_denominator": {
            "n_total": metrics["n_total"],
            "valid_n": metrics["graded"],
            "failed": metrics["failed"],
            "missing": metrics["missing"],
            "denominator_includes_failures": metrics["denominator_includes_failures"],
        },
        "sample_count": len(samples),
        "samples": samples,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "clean-aisle-baseline-v1.manifest.json"
    dump(manifest_path, manifest)
    manifest_sha = sha256_file(manifest_path)

    raw_list = {
        "schema": "truckflow-clean-baseline-raw-list-v1",
        "route_id": ROUTE["id"],
        "count": len(samples),
        "files": [
            {
                "sample_id": row["sample_id"],
                "path": row["path"],
                "sha256": row["sha256"],
                "bytes": row["bytes"],
            }
            for row in samples
        ],
    }
    raw_path = out_dir / "clean-aisle-baseline-v1.raw-list.json"
    dump(raw_path, raw_list)
    raw_sha = sha256_file(raw_path)

    summary = {
        "schema": "truckflow-route-summary-v1",
        "route": ROUTE,
        "published_on": args.today,
        "dataset": manifest["dataset"],
        "camera_count": {
            "n_total": metrics["n_total"],
            "valid_n": metrics["graded"],
            "failed": metrics["failed"],
            "missing": metrics["missing"],
            "exact": metrics["exact"],
            "mae": metrics["mae_graded"],
            "under": metrics["under"],
            "over": metrics["over"],
            "exact_rate_valid": metrics["exact_rate_graded"] / 100.0,
            "exact_rate_total": metrics["exact_rate_all"] / 100.0,
            "metric_scope": (
                "total visible truck count per camera; "
                "not vehicle ID, vehicle class, unique-set or overlap accuracy"
            ),
        },
        "unique": {
            "n_total": 10,
            "valid_n": None,
            "failed": None,
            "missing": None,
            "exact": None,
            "mae": None,
            "status": "not measured",
            "note": "This route emits per-camera counts only.",
        },
        "overlap": {
            "n_total": 10,
            "valid_n": None,
            "failed": None,
            "missing": None,
            "exact": None,
            "mae": None,
            "status": "not measured",
            "note": "No overlap prediction is produced.",
        },
        "release": {
            "n_total": 20,
            "auto_released": None,
            "correct": None,
            "errors": None,
            "coverage": None,
            "status": "not measured",
            "note": "No review or auto-release policy is part of the raw baseline.",
        },
        "review": {
            "reviewed": None,
            "review_rate": None,
            "status": "not measured",
        },
        "identity": {
            "status": "not measured",
            "n_total": None,
            "exact": None,
            "note": "Count exactness does not imply vehicle ID or class accuracy.",
        },
        "cost": {
            "calls": 20,
            "images": 20,
            "tokens_total": 67027,
            "latency_s_mean": 15.864,
            "latency_s_p95": 21.27,
            "concurrency": 1,
            "peak_memory_mb": None,
            "note": (
                "20 successful calls after the south_1200 rerun; "
                "retry attempts are excluded from this run set."
            ),
        },
        "workflow_audit": {
            "human_boxes_used_as_model_input": False,
            "same_frame_annotations_exposed": False,
            "future_frames_exposed": False,
            "memory_retrieval_scope": "none",
            "previous_count_carryover": False,
            "carryover_has_new_evidence": None,
            "failures_skipped": False,
            "failure_counted_in_denominator": True,
        },
        "manifest": {
            "file": manifest_path.name,
            "sha256": manifest_sha,
            "sample_count": len(samples),
        },
        "raw_list": {
            "file": raw_path.name,
            "sha256": raw_sha,
            "count": len(samples),
        },
        "evaluation": {
            "file": args.evaluation.as_posix(),
            "sha256": evaluation_sha,
            "run_set_sha256": evaluation["runs"]["run_set_sha256"],
        },
        "artifacts": {
            "runs": args.run_dir.as_posix(),
            "evaluation": args.evaluation.as_posix(),
            "report": "accuracy/REPORT_clean_baseline_v1.md",
            "evidence": "accuracy/evidence/clean_baseline/errors_contact.jpg",
            "provenance": "accuracy/runs/aisle_clean/_provenance.json",
        },
    }
    metrics_path = out_dir / "clean-aisle-baseline-v1.metrics.json"
    dump(metrics_path, summary)

    print(f"manifest: {manifest_path} sha256={manifest_sha}")
    print(f"metrics:  {metrics_path}")
    print(f"raw list: {raw_path} sha256={raw_sha}")
    print(f"samples:  {len(samples)} (fixed denominator {metrics['n_total']})")


if __name__ == "__main__":
    main()
