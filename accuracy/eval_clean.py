"""Evaluate one explicit view without mixing crops and without silent drops.

The review file is the source of truth. Every reviewed camera sample is a
denominator entry. A missing or failed run gets its own row and remains visible
in the summary; it is never treated as an exact match or silently removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VIEW_SUFFIX = {"aisle": "aisle"}
SAMPLE_RE = re.compile(r"^(north|south)_(\d+)_aisle\.json$")
GRID_MARKERS = ("grid", "band", "corridor", "lane", "far_door", "top")


class ContractError(RuntimeError):
    """Raised when a run directory violates the clean-evaluation contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_truth(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "truckflow-final-review-v2":
        raise ContractError(f"{path}: expected truckflow-final-review-v2")
    if not payload.get("complete"):
        raise ContractError(f"{path}: review export is not marked complete")

    truth: dict[str, dict[str, Any]] = {}
    unique_totals: list[str] = []
    for row in payload.get("samples", []):
        if not row.get("completed"):
            continue
        time_s = int(row["time"])
        counts = row.get("camera_counts") or {}
        for camera in ("north", "south"):
            value = counts.get(camera)
            if isinstance(value, int):
                sample_id = f"{camera}_{time_s}"
                if sample_id in truth:
                    raise ContractError(f"duplicate truth sample: {sample_id}")
                truth[sample_id] = {
                    "sample_id": sample_id,
                    "camera": camera,
                    "time_s": time_s,
                    "gold": value,
                }
        if isinstance(row.get("unique_total"), int):
            unique_totals.append(f"t{time_s}")

    if not truth:
        raise ContractError(f"{path}: no completed per-camera samples")
    return truth, unique_totals


def sample_sort_key(sample_id: str) -> tuple[str, int]:
    camera, time_s = sample_id.rsplit("_", 1)
    return camera, int(time_s)


def inspect_run_file(path: Path, view: str) -> tuple[str, dict[str, Any]]:
    lowered = path.name.lower()
    if any(marker in lowered for marker in GRID_MARKERS):
        raise ContractError(f"{path.name}: contains a non-{view} view marker")

    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.get("sample_id")
    match = SAMPLE_RE.fullmatch(path.name)
    if match:
        camera, time_s = match.groups()
        sample_id = f"{camera}_{time_s}"
    elif (
        isinstance(declared, str)
        and re.fullmatch(r"(?:north|south)_\d+", declared)
        and payload.get("view") == view
    ):
        sample_id = declared
    else:
        raise ContractError(
            f"{path.name}: not a {view!r}-only run file; expected "
            "<north|south>_<seconds>_aisle.json or a payload with "
            "sample_id and view='aisle'"
        )
    if declared is not None and declared != sample_id:
        raise ContractError(
            f"{path.name}: payload sample_id={declared!r} conflicts with {sample_id!r}"
        )
    declared_view = payload.get("view")
    if declared_view is not None and declared_view != view:
        raise ContractError(
            f"{path.name}: payload view={declared_view!r}, expected {view!r}"
        )

    image_name = Path(payload.get("image", "")).name
    if image_name and image_name != f"{sample_id}_{VIEW_SUFFIX[view]}.jpg":
        raise ContractError(
            f"{path.name}: image basename {image_name!r} is not the same "
            f"{view!r} view for {sample_id}"
        )

    runs = payload.get("runs") or []
    successful: list[dict[str, Any]] = []
    for run in runs:
        if not run.get("ok"):
            continue
        total = (run.get("parsed") or {}).get("counts", {}).get("total")
        if isinstance(total, int):
            successful.append(run)

    if successful:
        totals = {
            int(run["parsed"]["counts"]["total"])
            for run in successful
        }
        if len(totals) != 1:
            raise ContractError(
                f"{path.name}: successful runs disagree on total: {sorted(totals)}"
            )
        predicted = totals.pop()
        status = "ok"
        reason = None
        attempts = max(int(run.get("attempts", 1)) for run in successful)
        model = successful[-1].get("model")
    else:
        predicted = None
        status = "failed"
        attempts = max((int(run.get("attempts", 1)) for run in runs), default=0)
        model = runs[-1].get("model") if runs else None
        reason = runs[-1].get("error", "no successful run") if runs else "no runs"

    return sample_id, {
        "status": status,
        "predicted": predicted,
        "error": None if predicted is None else predicted,  # replaced after truth join
        "reason": reason,
        "attempts": attempts,
        "model": model,
        "path": path,
        "sha256": sha256(path),
    }


def load_runs(directory: Path, view: str, truth: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        raise ContractError(f"run directory does not exist: {directory}")

    runs: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        sample_id, record = inspect_run_file(path, view)
        if sample_id in runs:
            raise ContractError(
                "duplicate sample_id: "
                f"{sample_id} in {runs[sample_id]['path'].name} and {path.name}"
            )
        if sample_id not in truth:
            raise ContractError(f"{path.name}: sample_id {sample_id!r} is absent from review truth")
        runs[sample_id] = record
    return runs


def evaluate(
    review_path: Path,
    run_dir: Path,
    view: str,
) -> dict[str, Any]:
    truth, unique_totals = load_truth(review_path)
    runs = load_runs(run_dir, view, truth)

    rows: list[dict[str, Any]] = []
    for sample_id in sorted(truth, key=sample_sort_key):
        gold_record = truth[sample_id]
        run = runs.get(sample_id)
        if run is None:
            rows.append(
                {
                    **gold_record,
                    "predicted": None,
                    "error": None,
                    "status": "missing",
                    "reason": "no run file for this sample",
                    "attempts": 0,
                    "model": None,
                    "file": None,
                    "sha256": None,
                }
            )
            continue

        predicted = run["predicted"]
        error = None if predicted is None else predicted - gold_record["gold"]
        rows.append(
            {
                **gold_record,
                "predicted": predicted,
                "error": error,
                "status": run["status"],
                "reason": run["reason"],
                "attempts": run["attempts"],
                "model": run["model"],
                "file": relative(run["path"]),
                "sha256": run["sha256"],
            }
        )

    n_total = len(rows)
    graded_rows = [row for row in rows if row["status"] == "ok"]
    failed_rows = [row for row in rows if row["status"] == "failed"]
    missing_rows = [row for row in rows if row["status"] == "missing"]
    exact = sum(row["error"] == 0 for row in graded_rows)
    absolute_error = sum(abs(row["error"]) for row in graded_rows)
    mae = absolute_error / len(graded_rows) if graded_rows else None
    run_set = "\n".join(
        f"{row['sample_id']}:{row['sha256']}"
        for row in rows
        if row["sha256"] is not None
    )

    return {
        "schema": "truckflow-clean-evaluation-v1",
        "view": view,
        "review": {
            "file": relative(review_path),
            "sha256": sha256(review_path),
            "reviewed_camera_samples": n_total,
            "reviewed_unique_times": len(unique_totals),
            "unique_time_keys": unique_totals,
        },
        "runs": {
            "directory": relative(run_dir),
            "view_contract": (
                "exactly one <camera>_<seconds>_aisle.json per sample; "
                "grid/band/corridor/lane images are rejected"
            ),
            "run_set_sha256": hashlib.sha256(run_set.encode("utf-8")).hexdigest(),
        },
        "metrics": {
            "n_total": n_total,
            "denominator_includes_failures": True,
            "graded": len(graded_rows),
            "exact": exact,
            "exact_rate_graded": round(exact / len(graded_rows) * 100, 1)
            if graded_rows
            else None,
            "exact_rate_all": round(exact / n_total * 100, 1) if n_total else None,
            "mae_graded": round(mae, 3) if mae is not None else None,
            "mae_denominator_graded": len(graded_rows),
            "under": sum(max(0, -row["error"]) for row in graded_rows),
            "over": sum(max(0, row["error"]) for row in graded_rows),
            "failed": len(failed_rows),
            "missing": len(missing_rows),
        },
        "failures": [
            {
                "sample_id": row["sample_id"],
                "status": row["status"],
                "gold": row["gold"],
                "reason": row["reason"],
                "file": row["file"],
            }
            for row in rows
            if row["status"] != "ok"
        ],
        "rows": rows,
    }


def print_table(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(
        f"view={report['view']} N={metrics['n_total']} "
        f"graded={metrics['graded']} exact={metrics['exact']}/{metrics['graded']} "
        f"MAE={metrics['mae_graded']} under={metrics['under']} "
        f"over={metrics['over']} failed={metrics['failed']} "
        f"missing={metrics['missing']}"
    )
    print(f"{'sample':<14} {'gold':>5} {'pred':>5} {'err':>5}  status")
    print(f"{'-' * 14} {'-' * 5} {'-' * 5} {'-' * 5}  {'-' * 8}")
    for row in report["rows"]:
        predicted = "-" if row["predicted"] is None else str(row["predicted"])
        error = "-" if row["error"] is None else f"{row['error']:+d}"
        print(
            f"{row['sample_id']:<14} {row['gold']:>5} {predicted:>5} "
            f"{error:>5}  {row['status']}"
        )
    for failure in report["failures"]:
        print(
            f"FAIL {failure['sample_id']} [{failure['status']}]: "
            f"{failure['reason']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--view", choices=sorted(VIEW_SUFFIX), required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = evaluate(args.review, args.runs, args.view)
    except ContractError as exc:
        raise SystemExit(f"clean-evaluation contract violation: {exc}") from exc

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_table(report)
    print(f"wrote {args.json_out}")


if __name__ == "__main__":
    main()
