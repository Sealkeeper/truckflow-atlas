"""Run whole-frame, lane-crop and three-frame comparisons.

The model proposes physical vehicle candidates. Scripts only build evidence and
apply exact schema validation; there is no detector, segmentation or tracker.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from extract_frames import OBSERVATIONS
from model_client import ROOT, load_env, probe


WHOLE_PROMPT = """你是展会撤换展现场的货车清点专家。只依据这张整帧画面清点所有可见货车。

口径：
1. 同一辆车的车头、挂车和货厢只算一辆；与相邻车头分离的独立挂车算一辆。
2. 小汽车、面包车、叉车、手推车、人物、工程机械不计。
3. 只统计画面内实际可见车辆；远处或遮挡但仍能确定是货车时必须计入；完全看不见不猜。
4. 按整车轮廓与比例分 large（重卡/半挂/长货厢）、medium（中卡）、small（轻卡/厢车）；不确定写 unknown。
5. 对远处、边界、遮挡、疑似车头货厢拆分的候选设 uncertain=true。

bbox 使用 0-1 归一化 [x0,y0,x1,y1]，框住整辆可见车辆的联合外接框。
只输出严格 JSON：
{"counts":{"total":0,"large":0,"medium":0,"small":0,"unknown":0},"vehicles":[{"bbox":[0,0,0,0],"size":"large|medium|small|unknown","visible":"full|partial_top|partial_side|trailer_only","is_truck":true,"identity_clues":"颜色、货厢、车头、文字等证据","evidence":"画面位置与理由","uncertain":false}],"scene_notes":"","uncertain_reasons":[]}"""

LANE_PROMPT = """这是同一机位的过道区域放大裁剪，四周展台已被裁掉。请只依据图中可见内容清点货车。

重点检查远处小型、被柱子/车辆遮挡、只露出一部分的货车。计数单位必须是物理车辆：
同一辆车的车头、底盘和货厢只算一辆；两个候选若是同一车的车头与货厢，必须合并。
独立挂车/货厢算一辆。小汽车、面包车、叉车、手推车、人物不计。车型不确定写 unknown。
bbox 是相对本裁剪图的 0-1 坐标。只输出严格 JSON，schema 与整帧清点相同：
{"counts":{"total":0,"large":0,"medium":0,"small":0,"unknown":0},"vehicles":[{"bbox":[0,0,0,0],"size":"large|medium|small|unknown","visible":"full|partial_top|partial_side|trailer_only","is_truck":true,"identity_clues":"","evidence":"","uncertain":false}],"scene_notes":"","uncertain_reasons":[]}"""

STRIP_PROMPT = """这是一条同一机位在 t-10s、t、t+10s 的三个连续证据面板，从左到右排列。
请分别清点每帧，并利用颜色、货厢、车头、文字、朝向等语义判断车辆是否跨帧为同一物理车。
禁止用像素跟踪或根据上一帧数量填数；每帧计数必须有该帧可见证据。

输出严格 JSON：
{"frames":[{"panel":"left|center|right","counts":{"total":0,"large":0,"medium":0,"small":0,"unknown":0},"vehicles":[{"panel_index":0,"bbox":[0,0,0,0],"size":"large|medium|small|unknown","identity_clues":"","uncertain":false}]}],"links":[{"from":"left:0","to":"center:1","same_vehicle":"yes|no|uncertain","evidence":""}],"new_or_exited":[{"frame":"left|center|right","vehicle":"panel_index","event":"enter|exit|uncertain","evidence":""}],"review_reasons":[]}
bbox 是单个面板内的 0-1 坐标。"""


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def job_specs(modes: list[str]) -> list[dict[str, Any]]:
    frames = ROOT / "assets" / "frames"
    crops = ROOT / "assets" / "crops"
    strips = ROOT / "assets" / "strips"
    specs: list[dict[str, Any]] = []
    for camera, times in OBSERVATIONS.items():
        for base in times:
            obs_id = f"{camera}_{base}"
            if "whole" in modes:
                specs.append(
                    {
                        "mode": "whole",
                        "observation": obs_id,
                        "images": [frames / f"{camera}_t{base}.jpg"],
                        "prompt": WHOLE_PROMPT,
                    }
                )
            if "crop" in modes:
                specs.append(
                    {
                        "mode": "crop",
                        "observation": obs_id,
                        "images": [crops / f"{camera}_t{base}_lane.jpg"],
                        "prompt": LANE_PROMPT,
                    }
                )
            if "strip" in modes:
                specs.append(
                    {
                        "mode": "strip",
                        "observation": obs_id,
                        "images": [strips / f"{camera}_{base}_strip.jpg"],
                        "prompt": STRIP_PROMPT,
                    }
                )
    return specs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="whole,crop,strip")
    parser.add_argument("--whole-models", default="doubao,zhipu,aibox")
    parser.add_argument("--crop-models", default="doubao,zhipu,aibox")
    parser.add_argument("--strip-models", default="doubao,aibox")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_env()
    model_map = {
        "whole": args.whole_models.split(","),
        "crop": args.crop_models.split(","),
        "strip": args.strip_models.split(","),
    }
    out_dir = ROOT / "data" / "runs" / "primary"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for spec in job_specs(args.modes.split(",")):
        for model in model_map[spec["mode"]]:
            target = out_dir / f"{spec['observation']}_{spec['mode']}__{model}.json"
            previous_ok = False
            if target.exists():
                previous_ok = bool(load_json(target, {}).get("run", {}).get("ok"))
            if args.force or not previous_ok:
                tasks.append((spec, model.strip(), target))
    print(f"scheduled {len(tasks)} calls")

    def run(task: tuple[dict[str, Any], str, Path]) -> tuple[Path, dict[str, Any]]:
        spec, model, target = task
        result = probe(model, spec["images"], spec["prompt"], max_tokens=3600)
        payload = {
            "observation": spec["observation"],
            "mode": spec["mode"],
            "images": [str(path.relative_to(ROOT)) for path in spec["images"]],
            "prompt": spec["prompt"],
            "run": result,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target, result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, task) for task in tasks]
        for future in as_completed(futures):
            target, result = future.result()
            if result.get("ok"):
                parsed = result.get("parsed", {})
                if "frames" in parsed:
                    totals = [frame.get("counts", {}).get("total") for frame in parsed["frames"]]
                    print(f"{target.name}: panels={totals} latency={result['latency_s']}s")
                else:
                    print(
                        f"{target.name}: total={parsed.get('counts', {}).get('total')} "
                        f"latency={result['latency_s']}s"
                    )
            else:
                print(f"{target.name}: FAILED {result.get('status')} {result.get('error')}")
    print(f"evidence: {out_dir}")


if __name__ == "__main__":
    main()
