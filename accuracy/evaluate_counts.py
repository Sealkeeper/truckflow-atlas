from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_runs(directory: Path) -> dict[tuple[str, int], dict]:
    values = {}
    for path in directory.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = Path(payload.get("image", path)).stem
        parts = name.split("_")
        camera, time_text = parts[0], parts[1]
        values[(camera, int(time_text))] = payload
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path)
    parser.add_argument("--gold", type=Path, default=ROOT / "data/gold/camera_counts_v0.json")
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    truth = {(row["camera"], row["time"]): row for row in gold["samples"]}
    runs = load_runs(args.runs)
    rows = []
    for key, sample in sorted(truth.items()):
        payload = runs.get(key)
        if not payload:
            continue
        for run in payload["runs"]:
            if not run.get("ok"):
                continue
            predicted = run["parsed"].get("counts", {}).get("total")
            rows.append({
                "camera": key[0],
                "time": key[1],
                "model": run["model"],
                "gold": sample["total"],
                "predicted": predicted,
                "error": predicted - sample["total"],
            })
    if not rows:
        raise SystemExit("no matching successful runs")
    exact = sum(row["error"] == 0 for row in rows)
    mae = sum(abs(row["error"]) for row in rows) / len(rows)
    print(f"exact={exact}/{len(rows)} ({exact / len(rows):.1%}) mae={mae:.2f}")
    for row in rows:
        flag = "OK" if row["error"] == 0 else "ERR"
        print(f"{flag:3s} {row['camera']}_{row['time']:<4d} gold={row['gold']} pred={row['predicted']} err={row['error']:+d}")


if __name__ == "__main__":
    main()
