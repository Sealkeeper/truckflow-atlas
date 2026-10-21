"""Second-pass physical-entity confirmation and cross-camera entity graph."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from model_client import ROOT, load_env, probe


CONTACT_PROMPT = """这是一个机位同一原始帧切出的候选联系表。每格 C1、C2... 是互相重叠的局部窗口，
不是“一格必定一辆车”，同一格可能包含多辆，同一辆也可能出现在多格。

请建立该帧的物理车辆集合：
1. 每个物理车辆只列一次，并在 candidates 中列出显示它的所有窗口编号。
2. 一个窗口可同时归入多个物理车辆；只有同一车头/货厢绝不能拆成两辆。
3. 排除人物、叉车、轿车、展台、杂物；完全空窗也应 reject。
4. 只按窗口中实际可见的车顶、货厢、车头、颜色、文字和比例判断，不猜画面外。
5. 远处、遮挡、窗口边界或与你看到的其它窗口有歧义时 review=true。
6. 车型按 large（重卡/半挂/长货厢）、medium（中卡）、small（轻卡/厢车）；不能确认写 unknown。

只输出严格 JSON：
{"physical_vehicles":[{"group":"G1","candidates":["C1","C3"],"size":"large|medium|small|unknown","identity":"颜色/货厢/车头/文字等可复核证据","reason":"为何这些窗口是同一物理车","review":false}],"rejected_candidates":[{"candidate":"C5","reason":""}],"review_reasons":[]}"""


PAIR_PROMPT = """这张联系表上排 N1... 是北机位在同一时刻的候选窗口，下排 S1... 是南机位的候选窗口。
两机位存在重叠，但视角和尺度不同。每格是互相重叠的窗口，不是“一格必定一辆车”。

请建立跨机位物理实体图：
1. 全图每个物理车辆只列一次，members 写出所有显示它的 N/S 窗口。
2. 只有当颜色、货厢结构、车头、文字、顶部特征等至少两个语义证据一致时，才判为跨机位同一车。
3. 同一辆车的车头与货厢不得分开；一个窗口可归入多个物理车辆。
4. 排除人物、叉车、轿车、空窗、展台。
5. 视角改变导致无法确认时写 match="uncertain" 且 review=true；不能为凑数强行配对。
6. 车型 large/medium/small/unknown。

输出严格 JSON：
{"physical_vehicles":[{"group":"G1","members":["N1","S2"],"match":"north_only|south_only|same_across_cameras|uncertain","size":"large|medium|small|unknown","identity":"可复核的至少两个特征","review":false}],"unique_total":0,"rejected_candidates":[{"candidate":"N4","reason":""}],"review_reasons":[]}"""


def existing_ok(path: Path) -> bool:
    if not path.exists():
        return False
    return bool(json.loads(path.read_text(encoding="utf-8")).get("run", {}).get("ok"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="doubao,aibox")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_env()
    candidates = json.loads((ROOT / "data" / "candidates.json").read_text(encoding="utf-8"))
    out_dir = ROOT / "data" / "runs" / "confirm"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    sheets = ROOT / "assets" / "sheets"
    for observation in candidates:
        jobs.append(
            {
                "job": f"{observation}_candidates",
                "image": sheets / f"{observation}_candidates.jpg",
                "prompt": CONTACT_PROMPT,
            }
        )
    for time_s in (600, 1200):
        jobs.append(
            {
                "job": f"pairs_{time_s}",
                "image": sheets / f"pairs_{time_s}.jpg",
                "prompt": PAIR_PROMPT,
            }
        )
    tasks: list[tuple[dict[str, Any], str, Path]] = []
    for job in jobs:
        for model in args.models.split(","):
            target = out_dir / f"{job['job']}__{model.strip()}.json"
            if args.force or not existing_ok(target):
                tasks.append((job, model.strip(), target))
    print(f"scheduled {len(tasks)} confirmation calls")

    def run(task: tuple[dict[str, Any], str, Path]) -> tuple[Path, dict[str, Any]]:
        job, model, target = task
        result = probe(model, [job["image"]], job["prompt"], max_tokens=5000)
        payload = {
            "job": job["job"],
            "image": str(job["image"].relative_to(ROOT)),
            "prompt": job["prompt"],
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
                print(
                    f"{target.name}: groups={len(parsed.get('physical_vehicles', []))} "
                    f"unique_total={parsed.get('unique_total')} latency={result['latency_s']}s"
                )
            else:
                print(f"{target.name}: FAILED {result.get('status')} {result.get('error')}")
    print(out_dir)


if __name__ == "__main__":
    main()
