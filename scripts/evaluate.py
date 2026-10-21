"""Evaluate frozen primary, contact-sheet and cross-camera evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

from model_client import ROOT


SIZES = ("large", "medium", "small", "unknown")


def read_run(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("run")


def size_counts(vehicles: list[dict[str, Any]], key: str = "size") -> dict[str, int]:
    result = {size: 0 for size in SIZES}
    for vehicle in vehicles:
        size = vehicle.get(key, "unknown")
        if size not in result:
            size = "unknown"
        result[size] += 1
    return result


def observation_result(gold: dict[str, Any], run: dict[str, Any], mode: str) -> dict[str, Any]:
    parsed = run.get("parsed", {})
    if mode == "strip":
        frames = parsed.get("frames", [])
        frame = next((item for item in frames if item.get("panel") == "center"), frames[1] if len(frames) > 1 else {})
        vehicles = frame.get("vehicles", [])
        predicted = frame.get("counts", {}).get("total", len(vehicles))
        review = bool(parsed.get("review_reasons")) or any(item.get("uncertain") for item in vehicles)
        review = review or any(link.get("same_vehicle") == "uncertain" for link in parsed.get("links", []))
    elif mode == "confirm":
        vehicles = parsed.get("physical_vehicles", [])
        predicted = len(vehicles)
        review = bool(parsed.get("review_reasons")) or any(item.get("review") for item in vehicles)
    else:
        vehicles = parsed.get("vehicles", [])
        predicted = parsed.get("counts", {}).get("total", len(vehicles))
        review = bool(parsed.get("uncertain_reasons")) or any(item.get("uncertain") for item in vehicles)
    gold_counts = gold["counts"]
    predicted_types = size_counts(vehicles)
    gold_types = {size: gold_counts[size] for size in SIZES}
    return {
        "observation": gold["id"],
        "gold_count": gold_counts["total"],
        "predicted_count": predicted,
        "count_absolute_error": abs(predicted - gold_counts["total"]),
        "count_exact": predicted == gold_counts["total"],
        "miss": max(0, gold_counts["total"] - predicted),
        "extra": max(0, predicted - gold_counts["total"]),
        "predicted_types": predicted_types,
        "type_abs_error": sum(abs(predicted_types[size] - gold_types[size]) for size in SIZES),
        "full_exact": predicted == gold_counts["total"] and predicted_types == gold_types,
        "review": review,
        "latency_s": run.get("latency_s"),
        "total_tokens": (run.get("usage") or {}).get("total_tokens"),
        "ok": bool(run.get("ok")),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row["ok"] and not row["review"]]
    latencies = [row["latency_s"] for row in rows if row.get("latency_s") is not None]
    tokens = [row["total_tokens"] for row in rows if row.get("total_tokens") is not None]
    return {
        "observations": len(rows),
        "completion_rate": round(sum(row["ok"] for row in rows) / max(1, len(rows)), 4),
        "auto_resolved": len(resolved),
        "auto_coverage": round(len(resolved) / max(1, len(rows)), 4),
        "review_rate": round(sum(bool(row["review"]) for row in rows) / max(1, len(rows)), 4),
        "count_exact": sum(bool(row["count_exact"]) and not row["review"] for row in rows),
        "raw_count_exact": sum(bool(row["count_exact"]) for row in rows),
        "raw_count_exact_rate": round(sum(bool(row["count_exact"]) for row in rows) / max(1, len(rows)), 4),
        "count_exact_rate": round(sum(bool(row["count_exact"]) and not row["review"] for row in rows) / max(1, len(rows)), 4),
        "count_exact_on_resolved": round(
            sum(row["count_exact"] for row in resolved) / max(1, len(resolved)), 4
        ),
        "full_exact": sum(bool(row["full_exact"]) and not row["review"] for row in rows),
        "raw_full_exact": sum(bool(row["full_exact"]) for row in rows),
        "raw_full_exact_rate": round(sum(bool(row["full_exact"]) for row in rows) / max(1, len(rows)), 4),
        "full_exact_rate": round(sum(bool(row["full_exact"]) and not row["review"] for row in rows) / max(1, len(rows)), 4),
        "full_exact_on_resolved": round(sum(row["full_exact"] for row in resolved) / max(1, len(resolved)), 4),
        "miss": sum(row["miss"] for row in rows),
        "extra": sum(row["extra"] for row in rows),
        "type_abs_error": sum(row["type_abs_error"] for row in rows),
        "non_large_type_assignments": sum(
            row["predicted_types"]["medium"]
            + row["predicted_types"]["small"]
            + row["predicted_types"]["unknown"]
            for row in rows
        ),
        "count_mae": round(mean(row["count_absolute_error"] for row in rows), 4),
        "mean_latency_s": round(mean(latencies), 3) if latencies else None,
        "latency_s": round(sum(latencies), 3),
        "tokens": sum(tokens),
    }


def main() -> None:
    gold_payload = json.loads((ROOT / "data" / "gold" / "temporal_gold.json").read_text(encoding="utf-8"))
    gold = {item["id"]: item for item in gold_payload["frames"]}
    observations = list(gold)
    primary = ROOT / "data" / "runs" / "primary"
    confirm = ROOT / "data" / "runs" / "confirm"
    all_rows: dict[str, list[dict[str, Any]]] = {}
    per_obs: list[dict[str, Any]] = []

    for mode in ("whole", "crop", "strip"):
        models = sorted({path.stem.rsplit("__", 1)[1] for path in primary.glob(f"*_{mode}__*.json")})
        for model in models:
            rows = []
            for observation in observations:
                run = read_run(primary / f"{observation}_{mode}__{model}.json")
                if run is None or not run.get("ok"):
                    row = {
                        "observation": observation,
                        "gold_count": gold[observation]["counts"]["total"],
                        "predicted_count": 0,
                        "count_absolute_error": gold[observation]["counts"]["total"],
                        "count_exact": False,
                        "miss": gold[observation]["counts"]["total"],
                        "extra": 0,
                        "predicted_types": {size: 0 for size in SIZES},
                        "type_abs_error": sum(gold[observation]["counts"][size] for size in SIZES),
                        "full_exact": False,
                        "review": True,
                        "latency_s": (run or {}).get("latency_s"),
                        "total_tokens": None,
                        "ok": False,
                    }
                else:
                    row = observation_result(gold[observation], run, mode)
                rows.append(row)
                per_obs.append({"strategy": f"{mode}/{model}", **row})
            all_rows[f"{mode}/{model}"] = rows

    confirm_models = sorted({path.stem.rsplit("__", 1)[1] for path in confirm.glob("*_candidates__*.json")})
    for model in confirm_models:
        rows = []
        for observation in observations:
            run = read_run(confirm / f"{observation}_candidates__{model}.json")
            if run is None or not run.get("ok"):
                row = {
                    "observation": observation,
                    "gold_count": gold[observation]["counts"]["total"],
                    "predicted_count": 0,
                    "count_absolute_error": gold[observation]["counts"]["total"],
                    "count_exact": False,
                    "miss": gold[observation]["counts"]["total"],
                    "extra": 0,
                    "predicted_types": {size: 0 for size in SIZES},
                    "type_abs_error": sum(gold[observation]["counts"][size] for size in SIZES),
                    "full_exact": False,
                    "review": True,
                    "latency_s": (run or {}).get("latency_s"),
                    "total_tokens": None,
                    "ok": False,
                }
            else:
                row = observation_result(gold[observation], run, "confirm")
            rows.append(row)
            per_obs.append({"strategy": f"confirm/{model}", **row})
        all_rows[f"confirm/{model}"] = rows

    # Two-model contact consensus: emit a result only when counts and type
    # distributions agree and both models have no review flag.
    if {"doubao", "aibox"}.issubset(confirm_models):
        rows = []
        for observation in observations:
            left = observation_result(gold[observation], read_run(confirm / f"{observation}_candidates__doubao.json") or {"ok": False}, "confirm")
            right = observation_result(gold[observation], read_run(confirm / f"{observation}_candidates__aibox.json") or {"ok": False}, "confirm")
            agree = (
                left["ok"]
                and right["ok"]
                and left["predicted_count"] == right["predicted_count"]
                and left["predicted_types"] == right["predicted_types"]
                and not left["review"]
                and not right["review"]
            )
            row = dict(left)
            row["review"] = not agree
            row["predicted_count"] = left["predicted_count"] if agree else -1
            row["count_exact"] = bool(agree and left["count_exact"])
            row["full_exact"] = bool(agree and left["full_exact"])
            row["count_absolute_error"] = abs(row["predicted_count"] - row["gold_count"]) if agree else row["gold_count"]
            row["miss"] = max(0, row["gold_count"] - row["predicted_count"]) if agree else row["gold_count"]
            row["extra"] = max(0, row["predicted_count"] - row["gold_count"]) if agree else 0
            row["type_abs_error"] = left["type_abs_error"] if agree else left["type_abs_error"] + 1
            row["latency_s"] = left["latency_s"] + right["latency_s"]
            row["total_tokens"] = left["total_tokens"] + right["total_tokens"]
            rows.append(row)
            per_obs.append({"strategy": "confirm/consensus2", **row})
        all_rows["confirm/consensus2"] = rows

    summaries = {strategy: aggregate(rows) for strategy, rows in all_rows.items()}

    cross: list[dict[str, Any]] = []
    for item in gold_payload["cross_camera"]:
        time_s = item["time_s"]
        naive = sum(item["per_camera_total"].values())
        for model in sorted(
            {path.stem.rsplit("__", 1)[1] for path in confirm.glob(f"pairs_{time_s}__*.json")}
        ):
            run = read_run(confirm / f"pairs_{time_s}__{model}.json")
            parsed = (run or {}).get("parsed", {})
            predicted = parsed.get("unique_total", len(parsed.get("physical_vehicles", [])))
            review = bool(parsed.get("review_reasons")) or any(
                vehicle.get("review") for vehicle in parsed.get("physical_vehicles", [])
            )
            cross.append(
                {
                    "time_s": time_s,
                    "model": model,
                    "gold_unique": item["unique_total"],
                    "naive_sum": naive,
                    "predicted_unique": predicted,
                    "predicted_duplicates": naive - predicted,
                    "gold_duplicates": naive - item["unique_total"],
                    "count_exact": predicted == item["unique_total"],
                    "review": review,
                    "latency_s": (run or {}).get("latency_s"),
                    "tokens": ((run or {}).get("usage") or {}).get("total_tokens"),
                }
            )

    pair_dir = ROOT / "data" / "runs" / "pair_probes"
    pair_probes: list[dict[str, Any]] = []
    for path in sorted(pair_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = payload.get("run", {})
        answer = run.get("parsed", {}).get("answer") if run.get("ok") else None
        pair_probes.append(
            {
                "case": payload.get("case"),
                "model": run.get("model"),
                "gold_answer": payload.get("gold_answer"),
                "answer": answer,
                "answer_exact": answer == payload.get("gold_answer"),
                "review": not run.get("ok")
                or bool(run.get("parsed", {}).get("review"))
                or answer == "uncertain",
                "latency_s": run.get("latency_s"),
                "tokens": (run.get("usage") or {}).get("total_tokens"),
            }
        )
    pair_summary = {
        "decisions": len(pair_probes),
        "exact": sum(row["answer_exact"] for row in pair_probes),
        "exact_rate": round(sum(row["answer_exact"] for row in pair_probes) / max(1, len(pair_probes)), 4),
        "review_rate": round(sum(row["review"] for row in pair_probes) / max(1, len(pair_probes)), 4),
        "positive_exact": sum(row["answer_exact"] for row in pair_probes if row["gold_answer"] == "yes"),
        "positive_total": sum(row["gold_answer"] == "yes" for row in pair_probes),
        "negative_exact": sum(row["answer_exact"] for row in pair_probes if row["gold_answer"] == "no"),
        "negative_total": sum(row["gold_answer"] == "no" for row in pair_probes),
        "latency_s": round(sum(row["latency_s"] or 0 for row in pair_probes), 3),
        "tokens": sum(row["tokens"] or 0 for row in pair_probes),
    }

    result = {
        "gold_version": gold_payload["version"],
        "sample_size": len(observations),
        "warning": "Small frozen development set. Count gold is verified; type gold is provisional single-annotator review. These results do not establish field accuracy.",
        "strategies": summaries,
        "cross_camera": cross,
        "pair_probes": pair_probes,
        "pair_probe_summary": pair_summary,
        "cross_camera_naive_duplicate_rate": round(
            sum(row["gold_duplicates"] for row in cross) / max(1, sum(row["naive_sum"] for row in cross)), 4
        ),
    }
    out_dir = ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "per_observation.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_obs[0]))
        writer.writeheader()
        for row in per_obs:
            copy = dict(row)
            copy["predicted_types"] = json.dumps(copy["predicted_types"], sort_keys=True)
            writer.writerow(copy)
    for strategy, metrics in sorted(summaries.items()):
        print(
            f"{strategy:24s} count_exact={metrics['count_exact']}/{metrics['observations']} "
            f"raw_count={metrics['raw_count_exact']}/{metrics['observations']} "
            f"full={metrics['full_exact']}/{metrics['observations']} "
            f"review={metrics['review_rate']:.0%} MAE={metrics['count_mae']:.2f} "
            f"miss={metrics['miss']} extra={metrics['extra']} latency={metrics['latency_s']:.1f}s"
        )
    for row in cross:
        print(
            f"pairs_{row['time_s']}/{row['model']}: {row['predicted_unique']} unique "
            f"(gold {row['gold_unique']}, naive {row['naive_sum']}) review={row['review']}"
        )
    print(
        f"pair probes: exact={pair_summary['exact']}/{pair_summary['decisions']} "
        f"positive={pair_summary['positive_exact']}/{pair_summary['positive_total']} "
        f"negative={pair_summary['negative_exact']}/{pair_summary['negative_total']} "
        f"review={pair_summary['review_rate']:.0%}"
    )
    print(out_dir / "metrics.json")


if __name__ == "__main__":
    main()
