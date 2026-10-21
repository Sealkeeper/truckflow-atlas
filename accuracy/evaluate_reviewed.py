from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_review(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema")
    if schema not in {"truckflow-final-review-v1", "truckflow-final-review-v2"}:
        raise SystemExit("review file schema mismatch")
    per_camera: dict[str, int] = {}
    unique_totals: dict[str, int] = {}
    for row in payload["samples"]:
        if schema == "truckflow-final-review-v1":
            if not row.get("reviewed"):
                continue
            per_camera[row["key"]] = int(row["final_total"])
            continue

        if not row.get("completed"):
            continue
        time_seconds = int(row["time"])
        counts = row.get("camera_counts") or {}
        for camera in ("north", "south"):
            value = counts.get(camera)
            if isinstance(value, int):
                per_camera[f"{camera}_{time_seconds}"] = value
        unique = row.get("unique_total")
        if isinstance(unique, int):
            unique_totals[str(time_seconds)] = unique
    if not per_camera:
        raise SystemExit("review file has no confirmed samples")
    return per_camera, unique_totals


def read_count(payload: dict[str, Any]) -> int | None:
    if isinstance(payload.get("predicted_count"), int):
        return payload["predicted_count"]
    for run in payload.get("runs", []):
        if run.get("ok"):
            total = run.get("parsed", {}).get("counts", {}).get("total")
            return int(total) if isinstance(total, int) else None
    return None


def load_runs(directory: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = payload.get("sample_id")
        if not sample_id:
            image = Path(payload.get("image", path)).stem
            parts = image.split("_")
            if len(parts) < 2:
                continue
            sample_id = f"{parts[0]}_{parts[1]}"
        count = read_count(payload)
        if count is not None:
            values[sample_id] = count
    return values


def evaluate(truth: dict[str, int], runs: dict[str, int]) -> dict[str, Any]:
    rows = []
    for key, gold in sorted(truth.items()):
        if key not in runs:
            continue
        predicted = runs[key]
        rows.append(
            {
                "key": key,
                "gold": gold,
                "predicted": predicted,
                "error": predicted - gold,
            }
        )
    if not rows:
        return {"graded": 0}
    exact = sum(row["error"] == 0 for row in rows)
    mae = sum(abs(row["error"]) for row in rows) / len(rows)
    return {
        "graded": len(rows),
        "exact": exact,
        "exact_rate": round(exact / len(rows) * 100, 1),
        "mae": round(mae, 3),
        "under": sum(max(0, -row["error"]) for row in rows),
        "over": sum(max(0, row["error"]) for row in rows),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--runs", type=Path, action="append", required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    truth, unique_totals = load_review(args.review)
    report: dict[str, Any] = {
        "reviewed_camera_samples": len(truth),
        "reviewed_unique_times": len(unique_totals),
        "unique_totals": unique_totals,
        "models": {},
    }
    for directory in args.runs:
        report["models"][directory.name] = evaluate(truth, load_runs(directory))

    for name, metrics in report["models"].items():
        if not metrics.get("graded"):
            print(f"{name}: no matching runs")
            continue
        print(
            f"{name}: exact={metrics['exact']}/{metrics['graded']} "
            f"({metrics['exact_rate']}%) mae={metrics['mae']} "
            f"under={metrics['under']} over={metrics['over']}"
        )
        for row in metrics["rows"]:
            if row["error"] != 0:
                print(
                    f"  ERR {row['key']:<14} reviewed={row['gold']} "
                    f"pred={row['predicted']} err={row['error']:+d}"
                )

    if args.json_out:
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
