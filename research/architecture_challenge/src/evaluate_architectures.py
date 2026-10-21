"""Aggregate the five-frame architecture challenge on one comparable table.

Metrics are recomputed from each saved run's final `counts`; they are not copied
from a mixed-version summary. The public Doubao whole-frame run is loaded from
its original JSON files so the baseline row has the same denominator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import PUBLIC, REPORTS, RUNS, load_gold, score, write_json


REQUIRED = [
    ("north", 300),
    ("north", 600),
    ("south", 600),
    ("north", 1200),
    ("south", 1200),
]

HUMAN_REVIEW = (
    PUBLIC / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
)

ARCHITECTURES = {
    "baseline_whole_frame": {
        "label": "Doubao whole frame",
        "path": PUBLIC / "accuracy" / "runs" / "count_v2" / "doubao_baseline_v1",
        "loader": "baseline",
    },
    "bands": {
        "label": "A: perspective depth bands",
        "path": RUNS / "bands",
        "loader": "run",
    },
    "windows": {
        "label": "A′: tight lane windows",
        "path": RUNS / "windows",
        "loader": "run",
    },
    "tree": {
        "label": "B: recursive region tree",
        "path": RUNS / "tree",
        "loader": "run",
    },
    "scene_graph": {
        "label": "C: lane scene graph",
        "path": RUNS / "scene_graph",
        "loader": "run",
    },
    "critic": {
        "label": "D: annotated critic loop",
        "path": RUNS / "critic",
        "loader": "run",
    },
}


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_human_counts() -> dict[tuple[str, int], int]:
    """Confirmed user review. It provides per-camera totals, not type splits."""
    payload = json.loads(HUMAN_REVIEW.read_text(encoding="utf-8"))
    counts: dict[tuple[str, int], int] = {}
    for sample in payload.get("samples") or []:
        if not sample.get("completed"):
            continue
        time_s = int(sample["time"])
        for camera, value in (sample.get("camera_counts") or {}).items():
            counts[(str(camera), time_s)] = int(value)
    return counts


def _baseline_counts(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("counts") or {}
    return {
        "total": int(payload.get("predicted_count") or raw.get("total") or 0),
        "large": int(raw.get("large") or 0),
        "medium": int(raw.get("medium") or 0),
        "small": int(raw.get("small") or 0),
        "unknown": int(raw.get("unknown") or 0),
    }


def _baseline_cost(payload: dict[str, Any]) -> dict[str, int | float]:
    usage = payload.get("usage") or {}
    return {
        "calls": 1,
        "failed_calls": 1 if payload.get("error") else 0,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "latency_s": round(float(payload.get("total_latency_ms") or 0) / 1000, 2),
    }


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile; avoids interpolating over few samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def summarize(
    architecture: str,
    spec: dict[str, Any],
    gold: dict[tuple[str, int], dict[str, Any]],
    human: dict[tuple[str, int], int],
    *,
    frames: list[tuple[str, int]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for camera, time_s in frames:
        sample = f"{camera}_{time_s}"
        payload = _read(spec["path"] / f"{sample}.json")
        human_total = human.get((camera, time_s))
        if human_total is None:
            raise KeyError(f"confirmed human total missing for {sample}")
        v0_gold = gold[(camera, time_s)]
        row: dict[str, Any] = {
            "sample": sample,
            "human_total": human_total,
            "v0_total": int(v0_gold["total"]),
            "v0_review": bool(v0_gold.get("review")),
            "present": payload is not None,
        }
        if payload is None:
            rows.append(row)
            continue
        counts = (
            _baseline_counts(payload)
            if spec["loader"] == "baseline"
            else payload["counts"]
        )
        metrics = score(gold[(camera, time_s)], counts)
        human_error = int(counts["total"]) - human_total
        cost = (
            _baseline_cost(payload)
            if spec["loader"] == "baseline"
            else payload.get("cost") or {}
        )
        input_images = (
            sum(len(call.get("images") or []) for call in payload.get("calls") or [])
            if spec["loader"] == "run"
            else 1
        )
        row.update(
            counts=counts,
            count_error=human_error,
            count_exact=human_error == 0,
            miss=max(0, -human_error),
            extra=max(0, human_error),
            v0_count_error=metrics["count_error"],
            v0_count_exact=metrics["count_error"] == 0,
            v0_type_exact=metrics["class_l1"] == 0,
            v0_full_exact=metrics["exact"],
            v0_class_l1=metrics["class_l1"],
            cost=cost,
            input_images=input_images,
            wall_s=payload.get("wall_s"),
        )
        rows.append(row)

    present = [row for row in rows if row.get("present")]
    n = len(present)
    denominator = max(1, n)
    required = max(1, len(frames))
    costs = [row.get("cost") or {} for row in present]
    latencies = [float(cost.get("latency_s") or 0) for cost in costs]
    walls = [
        float(row.get("wall_s") or (row.get("cost") or {}).get("latency_s") or 0)
        for row in present
    ]
    return {
        "architecture": architecture,
        "label": spec["label"],
        "frames_required": len(frames),
        "frames_present": n,
        "valid_n": n,
        "count_exact_of_required": f"{sum(bool(row['count_exact']) for row in present)}/{len(frames)}",
        "count_exact_rate_of_required": round(
            100.0 * sum(bool(row["count_exact"]) for row in present) / required, 1
        ),
        "missing_samples": [
            row["sample"] for row in rows if not row.get("present")
        ],
        "failed_samples": [
            row["sample"]
            for row in present
            if int((row.get("cost") or {}).get("failed_calls") or 0) > 0
        ],
        "count_exact": sum(bool(row["count_exact"]) for row in present),
        # Valid-sample MAE (missing/failed samples excluded from the mean, but
        # still listed above and counted in the fixed required denominator).
        "count_mae": round(sum(abs(row["count_error"]) for row in present) / denominator, 3),
        "count_mae_fixed_denominator": round(
            sum(abs(row["count_error"]) for row in present) / required, 3
        ),
        "miss_units": sum(row["miss"] for row in present),
        "extra_units": sum(row["extra"] for row in present),
        "v0_count_exact": sum(bool(row["v0_count_exact"]) for row in present),
        "v0_full_exact": sum(bool(row["v0_full_exact"]) for row in present),
        "v0_type_exact": sum(bool(row["v0_type_exact"]) for row in present),
        "v0_class_l1": sum(row["v0_class_l1"] for row in present),
        "calls": sum(int(cost.get("calls") or 0) for cost in costs),
        "failed_calls": sum(int(cost.get("failed_calls") or 0) for cost in costs),
        "input_images": sum(int(row.get("input_images") or 0) for row in present),
        "prompt_tokens": sum(int(cost.get("prompt_tokens") or 0) for cost in costs),
        "completion_tokens": sum(
            int(cost.get("completion_tokens") or 0) for cost in costs
        ),
        "total_tokens": sum(int(cost.get("total_tokens") or 0) for cost in costs),
        "summed_call_latency_s": round(
            sum(float(cost.get("latency_s") or 0) for cost in costs), 2
        ),
        "call_latency_mean_s": round(sum(latencies) / denominator, 2),
        "call_latency_p95_s": _percentile(latencies, 0.95),
        "wall_mean_s": round(sum(walls) / denominator, 2),
        "wall_p95_s": _percentile(walls, 0.95),
        "summed_wall_s": round(
            sum(
                float(row.get("wall_s") or (row.get("cost") or {}).get("latency_s") or 0)
                for row in present
            ),
            2,
        ),
        "rows": rows,
    }


def markdown(summary: dict[str, Any]) -> str:
    frames = [tuple(item.rsplit("_", 1)) for item in summary["frames"]]
    frames = [(camera, int(time_s)) for camera, time_s in frames]
    regression = len(frames) == 20
    lines = [
        "# Architecture challenge evaluation",
        "",
        "Primary truth: `accuracy/reviewed/user-final-review-v2-2026-10-21.json` "
        "(confirmed user review, per-camera totals).",
        "Required frames: " + ", ".join(f"{c}_{t}" for c, t in frames),
        (
            "This is the 20-camera regression set (development data)."
            if regression
            else "This is a five-frame diagnostic set, not the 20-frame regression set."
        ),
        "",
        "| Architecture | Valid / required | Human count exact (of required) | Count MAE (valid) | Miss | Extra | v0 full exact (diag) | v0 type exact (diag) | Calls | Failed | Images | Tokens | Wall mean s | Wall p95 s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["architectures"]:
        lines.append(
            "| {label} | {frames_present}/{frames_required} | {count_exact_of_required} | "
            "{count_mae:.3f} | {miss_units} | {extra_units} | {v0_full_exact} | "
            "{v0_type_exact} | {calls} | {failed_calls} | {input_images} | "
            "{total_tokens} | {wall_mean_s:.1f} | {wall_p95_s:.1f} |".format(**item)
        )
    lines += ["", "## Per-frame total counts (human / prediction)", ""]
    lines.append("| Architecture | " + " | ".join(f"{c}_{t}" for c, t in frames) + " |")
    lines.append("|---|" + "---:|" * len(frames))
    for item in summary["architectures"]:
        by_sample = {row["sample"]: row for row in item["rows"]}
        cells = []
        for camera, time_s in frames:
            row = by_sample[f"{camera}_{time_s}"]
            if not row.get("present"):
                cells.append("missing")
            else:
                cells.append(f"{row['human_total']} / {row['counts']['total']}")
        lines.append(f"| {item['label']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "The human v2 export contains totals only, so type accuracy is not a "
        "confirmed metric. The v0 full/type columns use the older provisional "
        "`camera_counts_v0` labels and are diagnostic only.",
    ]
    baseline = summary.get("baseline_20_frame")
    if baseline and not regression:
        lines += [
            "",
            "## 20-frame regression set (baseline only)",
            "",
            f"Doubao whole frame: {baseline['count_exact_of_required']} human count exact, "
            f"MAE {baseline['count_mae']:.3f}, "
            f"miss {baseline['miss_units']}, extra {baseline['extra_units']}.",
        ]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--architectures",
        default=",".join(ARCHITECTURES),
        help="Comma-separated architecture keys",
    )
    parser.add_argument("--out", default=str(REPORTS / "evaluation_latest.json"))
    parser.add_argument("--markdown-out", default=str(REPORTS / "evaluation_latest.md"))
    parser.add_argument(
        "--frame-set",
        choices=("diagnostic", "regression20"),
        default="diagnostic",
        help="diagnostic = fixed five frames; regression20 = all 20 human-review samples",
    )
    args = parser.parse_args()

    gold = load_gold()
    human = load_human_counts()
    selected = [name.strip() for name in args.architectures.split(",") if name.strip()]
    frames = (
        sorted(human, key=lambda item: (item[1], item[0]))
        if args.frame_set == "regression20"
        else REQUIRED
    )
    summary = {
        "frame_set": args.frame_set,
        "required_frames": [f"{c}_{t}" for c, t in frames],
        "frames": [f"{c}_{t}" for c, t in frames],
        "architectures": [
            summarize(name, ARCHITECTURES[name], gold, human, frames=frames)
            for name in selected
        ],
        "baseline_20_frame": summarize(
            "baseline_whole_frame",
            ARCHITECTURES["baseline_whole_frame"],
            gold,
            human,
            frames=sorted(human, key=lambda item: (item[1], item[0])),
        ),
        "human_review_source": str(HUMAN_REVIEW),
        "gold_v0_source": str(PUBLIC / "data" / "gold" / "camera_counts_v0.json"),
    }
    write_json(Path(args.out), summary)
    markdown_path = Path(args.markdown_out)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))


if __name__ == "__main__":
    main()
