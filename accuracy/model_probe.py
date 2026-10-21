"""Probe vision-model counting behaviour on a single frame.

This is an accuracy experiment, not a detector. The model returns the candidate
set; deterministic code only validates the schema and records raw evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


PROMPT = """你是展会撤换展现场的货车清点专家。只依据这张画面，清点所有可见货车。

计数口径：
1. 货车包括重型牵引车、半挂车、厢式货车、轻型/中型货车。
2. 同一辆车的车头与货厢只算一辆；单独清晰可见的挂车/货厢，如果它与相邻车头不是同一辆，也算一辆。
3. 小汽车、面包车、叉车、手推车、工程机械、人物都不计入。
4. 只统计画面内实际可见的车辆。不要猜测画面外或被完全遮挡的车。
5. 车身只露出局部但仍能确定是货车时计入，并在 visible 字段说明；无法确定时 uncertain=true。
6. 按整车外形与比例分为 large（重卡/半挂/长货厢）、medium（中卡）、small（轻卡/厢车）。不确定不要硬分。
7. 不要因为车辆在通道边缘、被柱子遮挡或靠近另一辆车而漏计。

坐标使用 0-1 归一化 [x0,y0,x1,y1]，框住整辆可见车辆的联合外接框。
输出严格 JSON，不要 markdown，不要额外解释：
{
  "counts": {"total": 0, "large": 0, "medium": 0, "small": 0, "unknown": 0},
  "vehicles": [
    {
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "is_truck": true,
      "identity_clues": "颜色、货厢/车头特征、朝向等可用于跨帧/跨机位匹配的线索",
      "evidence": "画面中的定位与判定理由",
      "uncertain": false
    }
  ],
  "scene_notes": "遮挡、边界车辆、可能的重复或歧义",
  "uncertain_reasons": []
}
"""


def data_uri(image: Path) -> str:
    suffix = image.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/png" if suffix == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


MODELS = {
    "doubao": {
        "base": os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "key": "DOUBAO_API_KEY",
        "model": os.environ.get("DOUBAO_MODEL", "ep-20260828174616-dthpx"),
    },
    "zhipu": {
        "base": os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        "key": "ZHIPU_API_KEY",
        "model": os.environ.get("ZHIPU_MODEL", "glm-4.7"),
    },
    "aibox": {
        "base": os.environ.get("AIBOX_BASE_URL", "https://aibox.richaibox.com:2078/v1"),
        "key": "AIBOX_API_KEY",
        "model": os.environ.get("AIBOX_MODEL", "glm-5.3"),
    },
}


def probe(name: str, image_path: Path, prompt: str, max_tokens: int, retries: int = 3) -> dict[str, Any]:
    cfg = MODELS[name]
    api_key = os.environ.get(cfg["key"], "")
    if not api_key:
        return {"model": name, "ok": False, "error": f"missing {cfg['key']}"}

    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri(image_path)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    started = time.perf_counter()
    last_error: dict[str, Any] | None = None
    for attempt in range(retries):
        try:
            response = requests.post(
                cfg["base"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
            latency = round(time.perf_counter() - started, 2)
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            parsed = extract_json(content)
            return {
                "model": name,
                "model_id": cfg["model"],
                "attempts": attempt + 1,
                "ok": True,
                "latency_s": latency,
                "usage": body.get("usage"),
                "parsed": parsed,
                "raw_text": content,
            }
        except Exception as exc:  # keep raw failure as evidence
            status = getattr(getattr(exc, "response", None), "status_code", None)
            text = getattr(getattr(exc, "response", None), "text", "")
            last_error = {
                "model": name,
                "model_id": cfg["model"],
                "attempts": attempt + 1,
                "ok": False,
                "latency_s": round(time.perf_counter() - started, 2),
                "status": status,
                "error": f"{type(exc).__name__}: {exc}",
                "response_text": text[:2000],
            }
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    assert last_error is not None
    return last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--models", default="doubao,zhipu,aibox")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--prompt-file", type=Path)
    args = parser.parse_args()

    load_env(ENV_PATH)
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else PROMPT
    results = [probe(name.strip(), args.image.resolve(), prompt, args.max_tokens) for name in args.models.split(",")]
    payload = {"image": str(args.image.resolve()), "prompt_version": "truck-count-v1", "runs": results}
    out = args.out or (ROOT / "accuracy" / "runs" / f"{args.image.stem}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in results:
        if item.get("ok"):
            parsed = item["parsed"]
            counts = parsed.get("counts", {})
            vehicles = parsed.get("vehicles", [])
            print(
                f"{item['model']}: total={counts.get('total')} vehicles={len(vehicles)} "
                f"sizes={counts.get('large')}/{counts.get('medium')}/{counts.get('small')} "
                f"unknown={counts.get('unknown')} latency={item['latency_s']}s"
            )
        else:
            print(f"{item['model']}: FAILED status={item.get('status')} {item.get('error')}")
    print(f"evidence: {out}")


if __name__ == "__main__":
    main()
