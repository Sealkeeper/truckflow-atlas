"""Ask a vision model to track distinct trucks across a short frame stack."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests

from model_probe import ENV_PATH, MODELS, data_uri, extract_json, load_env


PROMPT = """你会看到同一机位、同一场景的三张连续画面，顺序为 t-10 秒、t、t+10 秒。
请把它们当作同一段短视频的关键帧，追踪其中的货车，而不是分别清点。

规则：
1. 同一辆实体货车在三帧中只输出一次，即使它中途被遮挡或只露出货厢。
2. 车头与自己的货厢/挂车属于同一辆；相邻但外观、位置或连接关系不同的货厢分别计数。
3. 正在装卸、移动缓慢、被前车遮挡的车辆仍然计入。
4. 叉车、小汽车、面包车、人物、手推车不计入。
5. 只统计画面中真实可见的车辆，不猜测画面外车辆。
6. 如果某辆车只在中间帧出现且无法与前后帧关联，可以列为独立实体，但 uncertain=true。
7. 车型按 large（重卡/半挂/长货厢）、medium（中卡）、small（轻卡/厢车）、unknown 分类；证据不足就 unknown。

每张图的坐标都是 0-1 归一化的 [x0,y0,x1,y1]。
严格输出 JSON，不要 markdown：
{
  "visible_counts": [{"frame_index": 0, "total": 0}, {"frame_index": 1, "total": 0}, {"frame_index": 2, "total": 0}],
  "unique_trucks": [
    {
      "track_id": "T1",
      "size": "large|medium|small|unknown",
      "presence": [true, true, true],
      "bbox_by_frame": [[0,0,0,0], [0,0,0,0], [0,0,0,0]],
      "identity_clues": "颜色、货厢纹理、车头、相对位置等",
      "uncertain": false,
      "evidence": "为什么这三处是同一辆或为什么它是独立车辆"
    }
  ],
  "unique_total": 0,
  "scene_notes": "遮挡、边界与可能的重复",
  "uncertain_reasons": []
}
"""


def call(model_name: str, images: list[Path], max_tokens: int) -> dict:
    cfg = MODELS[model_name]
    key = os.environ.get(cfg["key"], "")
    content = [{"type": "image_url", "image_url": {"url": data_uri(path)}} for path in images]
    content.append({"type": "text", "text": PROMPT})
    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    started = time.perf_counter()
    response = requests.post(
        cfg["base"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    latency = round(time.perf_counter() - started, 2)
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"]
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return {
        "model": model_name,
        "model_id": cfg["model"],
        "latency_s": latency,
        "usage": body.get("usage"),
        "parsed": extract_json(text),
        "raw_text": text,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", nargs=3, required=True, type=Path)
    parser.add_argument("--models", default="doubao")
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    load_env(ENV_PATH)
    runs = []
    for name in args.models.split(","):
        try:
            runs.append(call(name.strip(), args.images, args.max_tokens))
            parsed = runs[-1]["parsed"]
            print(
                f"{name}: unique={parsed.get('unique_total')} counts={parsed.get('visible_counts')} "
                f"latency={runs[-1]['latency_s']}s"
            )
        except Exception as exc:
            runs.append({"model": name, "ok": False, "error": repr(exc)})
            print(f"{name}: FAILED {exc!r}")
    out = args.out or ENV_PATH.parent / "accuracy" / "runs" / "temporal_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"images": [str(path) for path in args.images], "runs": runs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(out)


if __name__ == "__main__":
    main()
