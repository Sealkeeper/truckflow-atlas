"""Check which crop scales expose the stacked far containers, repeated twice."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import EVIDENCE, FRAMES, call_model, save_crop
from prompts import band_prompt


VIEWS = [
    ("full", [0.0, 0.0, 1.0, 1.0], 1600),
    ("corridor", [0.27, 0.04, 0.75, 1.0], 1600),
    ("far", [0.30, 0.08, 0.72, 0.46], 1800),
    ("near", [0.26, 0.50, 1.0, 1.0], 1600),
]


def main() -> None:
    frame = FRAMES / "north_600.jpg"
    out_dir = EVIDENCE / "smoke_multiview"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for name, box, long_side in VIEWS:
        path = out_dir / f"north600_{name}.jpg"
        save_crop(frame, box, path, pad=0.0, long_side=long_side, grid=False)
        for rep in range(2):
            tasks.append((name, box, path, rep))

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                call_model,
                band_prompt(name, box[1], box[3], 0.0, 1.0),
                [path],
                stage=f"{name}_r{rep}",
                max_tokens=1800,
            ): (name, box, rep)
            for name, box, path, rep in tasks
        }
        for future in as_completed(futures):
            name, box, rep = futures[future]
            call = future.result()
            parsed = call.get("parsed") or {}
            print(name, rep, parsed.get("counts"), call.get("latency_s"))
            for vehicle in parsed.get("vehicles", []):
                print("   ", vehicle.get("size"), vehicle.get("cargo_color"), vehicle.get("bbox"))
            results.append({"view": name, "rep": rep, "box": box, "call": call})
    (out_dir / "north600_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
