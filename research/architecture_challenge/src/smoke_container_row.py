"""Probe tight crops of the stacked container row on north_600."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import EVIDENCE, FRAMES, call_model, save_crop


PROMPT = """这是一段通道左侧的集装箱挂车队列，画面中可能有多节上下排列的货厢。
请逐节清点，不要因为它们是同一颜色、同一队列或看起来连在一起，就把两节货厢合并。

判据：
- 两节货厢之间是否有横向缝隙、不同高度的顶面、不同的后门/侧板纹理、不同编号、不同的底盘或支腿。
- 只要两节货厢的箱体边界清楚、颜色/纹理/编号不同，就分别计数。
- 牵引车+货厢算一辆；只看到独立运输挂车/货厢也算一辆。
- 展台、建筑、广告牌、货架、叉车、人物不计。

bbox 使用当前裁剪的 0-1 归一化坐标。
只输出 JSON：
{"counts":{"total":0,"large":0,"medium":0,"small":0},"vehicles":[{"bbox":[0,0,0,0],"size":"large|medium|small|unknown","cargo_color":"","distinct_from_above":"与上一节的区别","evidence":""}],"notes":""}"""


VARIANTS = [
    ("row_a", [0.37, 0.00, 0.60, 0.40]),
    ("row_b", [0.38, 0.10, 0.58, 0.44]),
    ("row_c", [0.39, 0.14, 0.57, 0.42]),
    ("row_d", [0.36, 0.00, 0.62, 0.45]),
]


def main() -> None:
    frame = FRAMES / "north_600.jpg"
    out_dir = EVIDENCE / "smoke_container_row"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for name, box in VARIANTS:
        path = out_dir / f"north600_{name}.jpg"
        save_crop(frame, box, path, pad=0.0, long_side=1600, grid=False)
        for rep in range(3):
            tasks.append((name, box, path, rep))
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(call_model, PROMPT, [path], stage=f"{name}_r{rep}", max_tokens=1400): (
                name,
                box,
                rep,
            )
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
