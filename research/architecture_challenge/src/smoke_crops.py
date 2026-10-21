"""Small crop/prompt sensitivity probe used before fixing the band contract."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import EVIDENCE, FRAMES, call_model, save_crop


PROMPT = """这张裁剪来自一台监控相机的同一帧，是一段货车通道的局部放大。
请清点裁剪里所有可见货车。牵引车+挂车算一辆；只看到独立运输挂车/集装箱货厢也算一辆。
展台、建筑、货架、叉车、轿车、面包车、人物不计。
蓝色/灰色的集装箱挂车要特别检查，不要当成展台。
只输出 JSON：
{"counts":{"total":0,"large":0,"medium":0,"small":0},"vehicles":[{"bbox":[0,0,0,0],"size":"large|medium|small|unknown","cargo_color":"","evidence":""}],"notes":""}"""


def main() -> None:
    frame = FRAMES / "north_600.jpg"
    out_dir = EVIDENCE / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    variants = [
        ("far_lane_grid", [0.34, 0.00, 0.66, 0.44], True),
        ("far_lane_nogrid", [0.34, 0.00, 0.66, 0.44], False),
        ("far_wide_nogrid", [0.28, 0.00, 0.74, 0.44], False),
        ("far_tight_nogrid", [0.37, 0.00, 0.60, 0.40], False),
        ("near_wide_nogrid", [0.26, 0.56, 1.00, 1.00], False),
        ("near_lane_nogrid", [0.30, 0.56, 0.72, 1.00], False),
    ]
    tasks = []
    for name, box, grid in variants:
        path = out_dir / f"north600_{name}.jpg"
        save_crop(frame, box, path, pad=0.0, long_side=1500, grid=grid)
        tasks.append((name, box, path))

    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(call_model, PROMPT, [path], stage=name, max_tokens=1800): (name, box)
            for name, box, path in tasks
        }
        for future in as_completed(futures):
            name, box = futures[future]
            call = future.result()
            results[name] = {"box": box, "call": call}
            parsed = call.get("parsed") or {}
            print(name, call.get("ok"), parsed.get("counts"), call.get("latency_s"))
            for vehicle in parsed.get("vehicles", []):
                print("   ", vehicle.get("size"), vehicle.get("cargo_color"), vehicle.get("evidence"))
            if not call.get("ok"):
                print("   ERROR", call.get("error"))
    (out_dir / "north600_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
