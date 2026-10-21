"""Bounded-call truck counting experiment.

Three configurations share one truth set and one single-pass output schema:
A  whole frame, one model call
B  fixed aisle crop, one model call
C  aisle call + at most one fixed far-zone call, only when the first response
   explicitly marks a possible miss

No detector or tracker is used.  Deterministic code only prepares fixed crops,
validates the response, maps the far-zone boxes back into aisle coordinates and
deduplicates model-returned entities by geometry.  Every HTTP request is
recorded, and every frame is capped at two requests.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TRUTH_PATH = ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
VIDEO_DIR = Path(r"D:\File\PROJECT\数据底座\数据底座-货车\视频")
VIDEOS = {
    "north": VIDEO_DIR / "A区天花北.mp4",
    "south": VIDEO_DIR / "A区天花南.mp4",
}
ENV_CANDIDATES = (
    ROOT / ".env",
    Path(r"D:\File\PROJECT\codex\codex-货车\codexcodex-货车\.env"),
)

CROP_ROOT = ROOT / "accuracy" / "crops" / "single_pass_v1"
RUN_ROOT = ROOT / "accuracy" / "runs" / "single_pass_v1"
EVIDENCE_ROOT = ROOT / "accuracy" / "evidence" / "single_pass_v1"

# Same fixed aisle geometry as the frozen baseline.  The far-zone crop is a
# fixed top slice of the aisle image, not a per-frame detector proposal.
AISLE_BOX = (350, 0, 870, 960)
AISLE_SCALE = 2
FAR_FRAC = 0.46
FAR_SCALE = 1.5

MODELS = {
    "doubao": {
        "base": os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "key": "DOUBAO_API_KEY",
        "model": os.environ.get("DOUBAO_MODEL", "ep-20260828174616-dthpx"),
    },
    "aibox-deepseek": {
        "base": os.environ.get("AIBOX_BASE_URL", "https://aibox.richaibox.com:2078/v1"),
        "key": "AIBOX_API_KEY",
        "model": "deepseek-v4.1-flash",
    },
}


MAIN_PROMPT = """你是展会撤换展现场的货车清点专家。你会一次看到{scope_name}。请一次性完成观察、逐车枚举、属性描述和覆盖率自检；不要分多轮，不要先给一个总数再回头补框。

统计范围
{scope_rules}

计数口径（与人工复核一致）
1. 画面内每个独立可辨的货车车体计 1 辆。
2. 牵引车与其直接连接的挂车/货厢合计算 1 辆，relation 写 cab_trailer_connected。
3. 看不到车头、但独立停放且可辨的货厢或集装箱挂车计 1 辆，relation 写 trailer_only。
4. 只有明确独立的货厢才单独计；只是同一辆车的货厢不能重复计。
5. 车身只露出局部但仍能确定是独立货车时计入，visibility 写 partial。
6. 叉车、轿车、面包车、手推车、工程机械、人物、展台结构、广告牌、堆叠纸箱、装卸货物不计。
7. 不猜测完全看不见的车辆。看见但无法确认是否为独立货车时，放进 coverage.uncertain_items，不要硬算。

单遍输出要求
- 直接在 vehicles 中列出每一辆你计入的车，同时令 counts.total 等于 vehicles 的数量。
- 每辆都给出 0-1 归一化 bbox [x0,y0,x1,y1]、车顶颜色、货厢颜色、车头/挂车关系、车型、画面可读文字、可见度和一句定位证据。
- 远端小目标、左右边缘、遮挡和并排处都要主动检查，并在 coverage 中如实声明本次覆盖边界。

覆盖率自检（关键）
- far_scanned：是否逐排检查了画面上部/远端的小车体与独立货厢。
- edge_scanned：是否检查了左右边缘被切掉一部分的车体。
- occlusion_scanned：是否检查了被立柱、其他车辆或人群遮挡的车体。
- far_objects_checked：你在远端/上部实际逐个数过的货厢/车体数量，包括已计入和未计入的。
- far_adjacency_verified：远端同一条排队列里，是否对每个相邻箱体的顶棚分界、尾门或底盘逐一确认过。看到一排相邻箱体但只确认了一个整体轮廓时必须为 false。
- possible_miss：当 far_adjacency_verified=false，或远端有箱体行但你无法逐个数清，或左右边缘/遮挡处仍有未解决候选时为 true。不要因为“已经看过那个区域”就自动设为 false；它表示仍有具体、可指出的漏计风险，而不是画面拥挤。
- miss_risk_regions：空数组，或从 ["far_top","left_edge","right_edge","occluded_mid","adjacent_pair"] 中选。
- uncertain_items：你看见但不敢计入的候选，逐项写区域、外观和不确定原因。
- 自检不是第二轮计数，只是声明这一遍观察的覆盖边界。

输出严格 JSON，不要 markdown，不要额外解释：
{{
  "vehicles": [
    {{
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "roof_color": "中文颜色或 unclear",
      "cargo_color": "中文颜色或 unclear",
      "relation": "cab_trailer_connected|rigid|trailer_only|unknown",
      "vehicle_type": "tractor_trailer|rigid_truck|box_truck|trailer_only|unknown",
      "readable_text": ["画面中可读的车牌/箱体文字，没有则空数组"],
      "visibility": "full|partial",
      "confidence": 0.0,
      "evidence": "画面中的位置、边界和为什么算一辆"
    }}
  ],
  "counts": {{"total": 0}},
  "coverage": {{
    "far_scanned": true,
    "edge_scanned": true,
    "occlusion_scanned": true,
    "far_objects_checked": 0,
    "far_adjacency_verified": true,
    "possible_miss": false,
    "miss_risk_regions": [],
    "uncertain_items": [],
    "notes": "本次扫描覆盖到哪里、哪里有边界风险"
  }},
  "scene_notes": "遮挡、并排、边缘和可能的歧义"
}}
"""


FAR_PROMPT = """你是展会撤换展现场的货车清点专家。这是一张固定的“远端易漏区”裁剪，取自同一帧中央通道的上半部（原通道归一化 y=0 到 0.46，横向不裁）。它只用于补查远端小目标、首尾相接和并排货厢，不是新的场景，也不要和主图相加。

先沿远端货厢行列逐个枚举“运输单元”，再把单元合并成物理车辆；仍然只做这一次调用。

第一阶段：枚举本裁剪中的运输单元。
- 带车头的货车、以及看不到车头但带底盘/车轮/支腿/牵引架的独立货厢，都是运输单元。
- 同一排队列里首尾相接的两个箱体，如果各有独立顶棚分界、后门或底盘/支腿，就是两个 unit，即使颜色相近、透视上连成一条纵列也不能合并。
- 蓝色、灰色波纹顶棚的箱体，只要能看出独立矩形轮廓、后门或支腿，就应按 unit 枚举；不要把它当成展台棚顶。
- 只从裁剪下边缘伸进来的近端大车不要枚举；它们应已由主图统计。
- 展台棚顶、背景板、广告牌、建筑结构、堆叠纸箱、装卸货物、人物、叉车、轿车不是运输单元。

第二阶段：把单元合并成车辆。
- 车头与它直接连接的货厢/挂车合计算 1 辆。
- 两个独立货厢各有自己的底盘/支腿/后门时，分别计 2 辆。
- 只看到货厢、无车头但独立停放时，vehicle_type=trailer_only。
- 同一辆车的车头与货厢绝不拆成两辆；不同车辆也不因外观相似而合并。
- 看不清独立箱体边界的远处色块不要硬算，写进 uncertain_items。

坐标使用相对本裁剪的 0-1 归一化。一次输出全部结果，counts.total 必须等于 vehicles 数量。
输出严格 JSON，不要 markdown：
{
  "units": [
    {
      "unit_id": "U1",
      "kind": "tractor_cab|cargo_box|trailer_chassis|box_truck|other",
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "color": "主要颜色",
      "evidence": "为什么它是本裁剪内的独立运输单元，与前后的分界在哪里"
    }
  ],
  "vehicles": [
    {
      "vehicle_id": "V1",
      "unit_ids": ["U1"],
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "roof_color": "中文颜色或 unclear",
      "cargo_color": "中文颜色或 unclear",
      "relation": "cab_trailer_connected|rigid|trailer_only|unknown",
      "vehicle_type": "tractor_trailer|rigid_truck|box_truck|trailer_only|unknown",
      "readable_text": [],
      "visibility": "full|partial",
      "confidence": 0.0,
      "evidence": "在本裁剪中的位置与独立边界"
    }
  ],
  "counts": {"total": 0},
  "uncertain_items": [],
  "scene_notes": "裁剪内遮挡与边界"
}
"""


def load_env() -> None:
    for path in ENV_CANDIDATES:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        break


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_truth() -> dict[str, dict[str, Any]]:
    payload = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "truckflow-final-review-v2":
        raise SystemExit("unexpected truth schema")
    rows: dict[str, dict[str, Any]] = {}
    for sample in payload["samples"]:
        if not sample.get("completed"):
            continue
        time_s = int(sample["time"])
        for camera in ("north", "south"):
            value = (sample.get("camera_counts") or {}).get(camera)
            if isinstance(value, int):
                rows[f"{camera}_{time_s}"] = {
                    "key": f"{camera}_{time_s}",
                    "camera": camera,
                    "time": time_s,
                    "truth": value,
                }
    return rows


def ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,r_frame_rate,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    body = json.loads(completed.stdout)
    stream = body["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": int(num) / int(den),
        "nb_frames": int(stream["nb_frames"]),
        "duration_seconds": float(body["format"]["duration"]),
    }


def extract_frame(video: Path, seconds: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        return
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ],
        check=True,
    )


def build_crop(source: Path, output: Path) -> None:
    with Image.open(source).convert("RGB") as image:
        left, top, right, bottom = AISLE_BOX
        crop = image.crop((left, top, right, bottom))
        crop = crop.resize(
            (crop.width * AISLE_SCALE, crop.height * AISLE_SCALE),
            Image.Resampling.LANCZOS,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output, quality=92, subsampling=0)


def build_far(source: Path, output: Path) -> None:
    with Image.open(source).convert("RGB") as image:
        crop = image.crop((0, 0, image.width, round(image.height * FAR_FRAC)))
        crop = crop.resize(
            (round(crop.width * FAR_SCALE), round(crop.height * FAR_SCALE)),
            Image.Resampling.LANCZOS,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output, quality=92, subsampling=0)


def build() -> None:
    truth = load_truth()
    meta: dict[str, Any] = {
        "version": "single-pass-v1",
        "truth": str(TRUTH_PATH.relative_to(ROOT)),
        "aisle_box_pixels": list(AISLE_BOX),
        "aisle_scale": AISLE_SCALE,
        "far_fraction_of_aisle": FAR_FRAC,
        "far_scale": FAR_SCALE,
        "offset_seconds": 0,
        "videos": {},
        "samples": [],
    }
    for camera, video in VIDEOS.items():
        meta["videos"][camera] = {"path": str(video), "sha256": sha256(video), **ffprobe(video)}

    for key, row in sorted(truth.items()):
        camera, time_s = row["camera"], row["time"]
        full = CROP_ROOT / "full" / f"{key}.jpg"
        aisle = CROP_ROOT / "aisle" / f"{key}.jpg"
        far = CROP_ROOT / "far" / f"{key}.jpg"
        extract_frame(VIDEOS[camera], time_s, full)
        build_crop(full, aisle)
        build_far(aisle, far)
        meta["samples"].append(
            {
                **row,
                "full": str(full.relative_to(ROOT)),
                "aisle": str(aisle.relative_to(ROOT)),
                "far": str(far.relative_to(ROOT)),
                "full_sha256": sha256(full),
                "aisle_sha256": sha256(aisle),
                "far_sha256": sha256(far),
            }
        )
    CROP_ROOT.mkdir(parents=True, exist_ok=True)
    (CROP_ROOT / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"built {len(meta['samples'])} frame triplets -> {CROP_ROOT}")


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


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


def call_model(
    model_name: str,
    image: Path,
    prompt: str,
    max_tokens: int = 3600,
    timeout: int = 150,
) -> dict[str, Any]:
    cfg = MODELS[model_name]
    api_key = os.environ.get(cfg["key"], "")
    if not api_key:
        return {"ok": False, "error": f"missing {cfg['key']}", "http_requests": 1}
    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri(image)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    started = time.perf_counter()
    try:
        response = requests.post(
            cfg["base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        latency = round(time.perf_counter() - started, 2)
        if response.status_code != 200:
            return {
                "ok": False,
                "http_status": response.status_code,
                "latency_s": latency,
                "error": response.text[:1200],
                "http_requests": 1,
            }
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        try:
            parsed = extract_json(text)
            parse_ok = True
            parse_error = None
        except Exception as exc:
            parsed = None
            parse_ok = False
            parse_error = f"{type(exc).__name__}: {exc}"
        return {
            "ok": True,
            "parse_ok": parse_ok,
            "parse_error": parse_error,
            "latency_s": latency,
            "usage": body.get("usage") or {},
            "parsed": parsed,
            "raw_text": text,
            "http_requests": 1,
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_s": round(time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "http_requests": 1,
        }


def main_prompt(scope: str) -> str:
    if scope == "full":
        return MAIN_PROMPT.format(
            scope_name="整帧画面",
            scope_rules=(
                "这是整帧画面。只统计画面中央南北向通道内的车辆：上端到画面顶部门洞，"
                "下端到画面底边，左右以两侧展台/货架边线为界。两侧展台、相邻通道、"
                "以及只从画面外缘露出的车辆或货厢不计。"
            ),
        )
    return MAIN_PROMPT.format(
        scope_name="固定中央通道裁剪",
        scope_rules=(
            "这是固定中央通道裁剪，整张图都属于统计范围。贴住上边缘、左右边缘或"
            "被立柱切掉一部分的车体也要检查；不要因为它们在边缘或尺寸小就漏计。"
        ),
    )


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) and math.isfinite(item) for item in value)
        and value[2] > value[0]
        and value[3] > value[1]
    )


def normalize_vehicles(
    parsed: dict[str, Any] | None, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    vehicles = parsed.get("vehicles")
    if not isinstance(vehicles, list):
        return []
    width, height = image_size
    normalized: list[dict[str, Any]] = []
    for item in vehicles:
        if not isinstance(item, dict) or not valid_bbox(item.get("bbox")):
            continue
        bbox = [float(value) for value in item["bbox"]]
        largest = max(bbox)
        if largest > 1.2:
            if largest <= 1005:
                bbox = [value / 1000 for value in bbox]
            else:
                bbox = [
                    bbox[0] / width,
                    bbox[1] / height,
                    bbox[2] / width,
                    bbox[3] / height,
                ]
        if not (bbox[2] > bbox[0] and bbox[3] > bbox[1]):
            continue
        copy = dict(item)
        copy["bbox"] = [round(max(0.0, min(1.0, value)), 4) for value in bbox]
        normalized.append(copy)
    return normalized


def iou(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(1e-9, area_a + area_b - inter)


def overlap_small(item: list[float], other: list[float]) -> float:
    ix0, iy0 = max(item[0], other[0]), max(item[1], other[1])
    ix1, iy1 = min(item[2], other[2]), min(item[3], other[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = (item[2] - item[0]) * (item[3] - item[1])
    return inter / max(1e-9, area)


def merge_far(
    primary: list[dict[str, Any]], far_vehicles: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged = [dict(item) for item in primary]
    added: list[dict[str, Any]] = []
    for item in far_vehicles:
        mapped = list(item["bbox"])
        mapped[1] *= FAR_FRAC
        mapped[3] *= FAR_FRAC
        duplicate = any(
            iou(mapped, other["bbox"]) > 0.25 or overlap_small(mapped, other["bbox"]) > 0.60
            for other in merged
        )
        if duplicate:
            continue
        copy = dict(item)
        copy["bbox"] = [round(value, 4) for value in mapped]
        copy["source"] = "far_zoom"
        merged.append(copy)
        added.append(copy)
    return merged, added


def result_count(vehicles: list[dict[str, Any]]) -> int:
    return len(vehicles)


def usage_tokens(run: dict[str, Any]) -> int:
    usage = run.get("usage") or {}
    value = usage.get("total_tokens")
    return int(value) if isinstance(value, (int, float)) else 0


def run_frame(sample: dict[str, Any], config: str, model_name: str) -> dict[str, Any]:
    if config == "A_full":
        image = ROOT / sample["full"]
        prompt = main_prompt("full")
    elif config == "B_aisle":
        image = ROOT / sample["aisle"]
        prompt = main_prompt("aisle")
    elif config == "C_adaptive":
        image = ROOT / sample["aisle"]
        prompt = main_prompt("aisle")
    else:
        raise ValueError(config)

    calls: list[dict[str, Any]] = []
    primary = call_model(model_name, image, prompt)
    calls.append({"kind": "primary", "image": str(image.relative_to(ROOT)), **primary})
    with Image.open(image) as opened:
        image_size = opened.size
    vehicles = normalize_vehicles(primary.get("parsed"), image_size)
    coverage = (primary.get("parsed") or {}).get("coverage") or {}
    triggered = False
    far_added: list[dict[str, Any]] = []
    if config == "C_adaptive" and primary.get("ok") and primary.get("parse_ok"):
        triggered = bool(coverage.get("possible_miss"))
        if triggered:
            far_image = ROOT / sample["far"]
            far = call_model(model_name, far_image, FAR_PROMPT)
            calls.append({"kind": "far_zoom", "image": str(far_image.relative_to(ROOT)), **far})
            with Image.open(far_image) as opened:
                far_size = opened.size
            far_vehicles = normalize_vehicles(far.get("parsed"), far_size)
            vehicles, far_added = merge_far(vehicles, far_vehicles)

    failure = not primary.get("ok") or not primary.get("parse_ok")
    degraded = any(not call.get("ok") or not call.get("parse_ok") for call in calls)
    return {
        "sample_id": sample["key"],
        "camera": sample["camera"],
        "time": sample["time"],
        "truth": sample["truth"],
        "config": config,
        "model": model_name,
        "prompt_version": "single-pass-v1" if config != "C_adaptive" else "single-pass-adaptive-v1",
        "prompt_sha256": prompt_digest(prompt),
        "images": [str((ROOT / sample["full" if config == "A_full" else "aisle"]).relative_to(ROOT))],
        "calls": calls,
        "call_count": len(calls),
        "http_requests": sum(int(call.get("http_requests") or 0) for call in calls),
        "triggered_far": triggered,
        "far_added": far_added,
        "vehicles": vehicles,
        "predicted_count": result_count(vehicles),
        "error": result_count(vehicles) - sample["truth"],
        "failure": failure,
        "degraded": degraded,
        "coverage": coverage,
        "latency_total_s": round(sum(float(call.get("latency_s") or 0) for call in calls), 2),
        "tokens_total": sum(usage_tokens(call) for call in calls),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def summarize(rows: list[dict[str, Any]], config: str) -> dict[str, Any]:
    graded = [row for row in rows if not row["failure"]]
    exact = sum(row["error"] == 0 for row in graded)
    mae = sum(abs(row["error"]) for row in graded) / len(graded) if graded else None
    calls = [row["call_count"] for row in rows]
    per_call_latencies = [
        float(call.get("latency_s") or 0)
        for row in rows
        for call in row["calls"]
        if call.get("ok")
    ]
    triggered = sum(bool(row["triggered_far"]) for row in rows)
    return {
        "config": config,
        "samples": len(rows),
        "graded": len(graded),
        "failures": len(rows) - len(graded),
        "exact": exact,
        "exact_rate_pct": round(exact / len(graded) * 100, 1) if graded else None,
        "mae": round(mae, 3) if mae is not None else None,
        "undercount": sum(max(0, -row["error"]) for row in graded),
        "overcount": sum(max(0, row["error"]) for row in graded),
        "avg_calls_per_frame": round(sum(calls) / len(calls), 3),
        "p95_calls_per_frame": percentile(calls, 0.95),
        "max_calls_per_frame": max(calls),
        "far_trigger_rate_pct": round(triggered / len(rows) * 100, 1),
        "far_triggered": triggered,
        "avg_frame_latency_s": round(sum(row["latency_total_s"] for row in rows) / len(rows), 2),
        "avg_call_latency_s": round(sum(per_call_latencies) / len(per_call_latencies), 2)
        if per_call_latencies
        else None,
        "p95_call_latency_s": round(percentile(per_call_latencies, 0.95), 2),
        "tokens_total": sum(row["tokens_total"] for row in rows),
        "avg_tokens_per_frame": round(sum(row["tokens_total"] for row in rows) / len(rows), 1),
    }


def config_dir(config: str, tag: str | None) -> Path:
    return RUN_ROOT / (f"{config}_{tag}" if tag else config)


def run_config(
    config: str,
    model_name: str,
    workers: int,
    keys: list[str] | None,
    force: bool,
    tag: str | None,
) -> None:
    load_env()
    truth = load_truth()
    manifest = json.loads((CROP_ROOT / "manifest.json").read_text(encoding="utf-8"))
    by_key = {sample["key"]: sample for sample in manifest["samples"]}
    selected = sorted(keys) if keys else sorted(truth)
    out_dir = config_dir(config, tag) / model_name
    out_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    for key in selected:
        out = out_dir / f"{key}.json"
        if out.exists() and not force:
            prior = json.loads(out.read_text(encoding="utf-8"))
            if not prior.get("failure"):
                continue
        pending.append(key)
    print(f"{config}/{model_name}: {len(selected) - len(pending)} complete, {len(pending)} pending")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_frame, by_key[key], config, model_name): key for key in pending}
        for future in as_completed(futures):
            key = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "sample_id": key,
                    "config": config,
                    "model": model_name,
                    "failure": True,
                    "call_count": 1,
                    "http_requests": 1,
                    "error_text": f"{type(exc).__name__}: {exc}",
                    "latency_total_s": 0,
                    "tokens_total": 0,
                    "calls": [],
                }
            (out_dir / f"{key}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            status = "FAIL" if row.get("failure") else f"{row.get('predicted_count')}/{row.get('truth')}"
            print(f"  {key:<14} {status} calls={row.get('call_count')} latency={row.get('latency_total_s')}s")


def collect(config: str, model_name: str, tag: str | None = None) -> list[dict[str, Any]]:
    directory = config_dir(config, tag) / model_name
    rows = []
    for path in sorted(directory.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def report(
    config: str, model_name: str, write: bool = True, tag: str | None = None
) -> dict[str, Any]:
    rows = collect(config, model_name, tag)
    summary = summarize(rows, config)
    if write:
        compact_rows = [
            {
                "sample_id": row["sample_id"],
                "truth": row["truth"],
                "predicted_count": row["predicted_count"],
                "error": row["error"],
                "call_count": row["call_count"],
                "triggered_far": row.get("triggered_far", False),
                "latency_total_s": row["latency_total_s"],
                "tokens_total": row["tokens_total"],
                "failure": row.get("failure", False),
            }
            for row in rows
        ]
        (config_dir(config, tag) / f"summary_{model_name}.json").write_text(
            json.dumps(
                {"summary": summary, "rows": compact_rows},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def aggregate(configs: list[str], model_name: str, tags: list[str]) -> dict[str, Any]:
    report_payload: dict[str, Any] = {
        "model": model_name,
        "truth": str(TRUTH_PATH.relative_to(ROOT)),
        "runs_per_config": len(tags),
        "configs": {},
    }
    for config in configs:
        runs = []
        all_rows = []
        for tag in tags:
            rows = collect(config, model_name, tag or None)
            if len(rows) != 20:
                continue
            for row in rows:
                row["run_tag"] = tag or "r1"
            all_rows.extend(rows)
            runs.append({"run": tag or "r1", **summarize(rows, config)})
        if not runs:
            continue
        metric_keys = (
            "exact",
            "exact_rate_pct",
            "mae",
            "undercount",
            "overcount",
            "avg_calls_per_frame",
            "avg_frame_latency_s",
            "avg_call_latency_s",
            "avg_tokens_per_frame",
            "tokens_total",
        )
        means = {
            key: round(sum(float(run[key]) for run in runs) / len(runs), 3)
            for key in metric_keys
            if all(isinstance(run.get(key), (int, float)) for run in runs)
        }
        per_frame: dict[str, dict[str, Any]] = {}
        trigger_rows = []
        for row in all_rows:
            entry = per_frame.setdefault(
                row["sample_id"],
                {
                    "truth": row["truth"],
                    "predictions": [],
                    "errors": [],
                    "calls": [],
                    "triggered": [],
                    "possible_miss": [],
                },
            )
            entry["predictions"].append(row["predicted_count"])
            entry["errors"].append(row["error"])
            entry["calls"].append(row["call_count"])
            entry["triggered"].append(bool(row.get("triggered_far")))
            entry["possible_miss"].append(bool((row.get("coverage") or {}).get("possible_miss")))
            if row.get("triggered_far"):
                trigger_rows.append(
                    {
                        "run": row.get("run_tag", ""),
                        "key": row["sample_id"],
                        "truth": row["truth"],
                        "predicted": row["predicted_count"],
                        "error": row["error"],
                        "far_added": len(row.get("far_added") or []),
                        "added": [
                            {
                                "roof_color": item.get("roof_color"),
                                "vehicle_type": item.get("vehicle_type"),
                                "bbox": item.get("bbox"),
                            }
                            for item in (row.get("far_added") or [])
                        ],
                    }
                )
        under_rows = [row for row in all_rows if row["error"] < 0]
        error_rows = [row for row in all_rows if row["error"] != 0]
        review_rows = [
            row for row in all_rows if bool((row.get("coverage") or {}).get("possible_miss"))
        ]
        auto_rows = [
            row for row in all_rows if not bool((row.get("coverage") or {}).get("possible_miss"))
        ]
        false_auto_rows = [row for row in auto_rows if row["error"] != 0]
        review_ids = {(row.get("run_tag"), row["sample_id"]) for row in review_rows}
        report_payload["configs"][config] = {
            "runs": runs,
            "means": means,
            "per_frame": per_frame,
            "trigger_audit": {
                "frames": len(all_rows),
                "possible_miss_true": sum(
                    bool((row.get("coverage") or {}).get("possible_miss")) for row in all_rows
                ),
                "undercount_frames": len(under_rows),
                "undercount_frames_flagged": sum(
                    bool((row.get("coverage") or {}).get("possible_miss"))
                    for row in under_rows
                ),
                "triggered_frames": len(trigger_rows),
                "trigger_rows": trigger_rows,
            },
            "aux_self_check_gate": {
                "note": "post-hoc only: possible_miss=true means review; false means auto-release; not a pre-registered production policy",
                "frames": len(all_rows),
                "error_frames": len(error_rows),
                "review_frames": len(review_rows),
                "review_rate_pct": round(len(review_rows) / len(all_rows) * 100, 2),
                "auto_release_frames": len(auto_rows),
                "false_release_frames": len(false_auto_rows),
                "false_release_rate_pct": round(len(false_auto_rows) / len(auto_rows) * 100, 2)
                if auto_rows
                else None,
                "error_frames_caught_by_review": sum(
                    (row.get("run_tag"), row["sample_id"]) in review_ids for row in error_rows
                ),
                "error_frame_coverage_pct": round(
                    sum(
                        (row.get("run_tag"), row["sample_id"]) in review_ids
                        for row in error_rows
                    )
                    / len(error_rows)
                    * 100,
                    2,
                )
                if error_rows
                else None,
            },
        }
    path = RUN_ROOT / f"aggregate_{model_name}.json"
    path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v["means"] for k, v in report_payload["configs"].items()}, ensure_ascii=False, indent=2))
    print(f"aggregate: {path}")
    return report_payload


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def draw_panel(
    image_path: Path,
    vehicles: list[dict[str, Any]],
    title: str,
    width: int = 560,
    height: int = 760,
) -> Image.Image:
    with Image.open(image_path).convert("RGB") as source:
        scale = min(width / source.width, height / source.height)
        resized = source.resize(
            (round(source.width * scale), round(source.height * scale)),
            Image.Resampling.LANCZOS,
        )
    panel = Image.new("RGB", (width, height + 58), (245, 245, 245))
    panel.paste(resized, ((width - resized.width) // 2, 58))
    draw = ImageDraw.Draw(panel)
    font = load_font(22)
    small = load_font(17)
    draw.text((10, 8), title, fill=(20, 20, 20), font=font)
    for index, vehicle in enumerate(vehicles, 1):
        bbox = vehicle.get("bbox") or []
        if len(bbox) != 4:
            continue
        x0 = (width - resized.width) // 2 + bbox[0] * resized.width
        y0 = 58 + bbox[1] * resized.height
        x1 = (width - resized.width) // 2 + bbox[2] * resized.width
        y1 = 58 + bbox[3] * resized.height
        draw.rectangle((x0, y0, x1, y1), outline=(255, 40, 40), width=4)
        draw.text((x0 + 3, max(60, y0 + 2)), str(index), fill=(255, 255, 0), font=small)
    return panel


def build_evidence(keys: list[str], model_name: str) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((CROP_ROOT / "manifest.json").read_text(encoding="utf-8"))
    by_key = {sample["key"]: sample for sample in manifest["samples"]}
    for key in keys:
        sample = by_key[key]
        a = json.loads((RUN_ROOT / "A_full" / model_name / f"{key}.json").read_text(encoding="utf-8"))
        b = json.loads((RUN_ROOT / "B_aisle" / model_name / f"{key}.json").read_text(encoding="utf-8"))
        c_candidates = []
        for tag in ("", "r2", "r3"):
            path = config_dir("C_adaptive", tag or None) / model_name / f"{key}.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["_run"] = tag or "r1"
                c_candidates.append(payload)
        c = max(c_candidates, key=lambda item: (item.get("call_count", 0), item.get("_run") == "r1"))
        panels = [
            draw_panel(
                ROOT / sample["full"],
                a["vehicles"],
                f"A full  {a['predicted_count']}/{a['truth']}  calls={a['call_count']}",
            ),
            draw_panel(
                ROOT / sample["aisle"],
                b["vehicles"],
                f"B aisle  {b['predicted_count']}/{b['truth']}  calls={b['call_count']}",
            ),
            draw_panel(
                ROOT / sample["aisle"],
                c["vehicles"],
                f"C adaptive {c['_run']}  {c['predicted_count']}/{c['truth']}  calls={c['call_count']}",
            ),
            draw_panel(
                ROOT / sample["far"],
                (c["calls"][1].get("parsed") or {}).get("vehicles", [])
                if len(c["calls"]) > 1
                else [],
                "C far zoom  triggered" if c["triggered_far"] else "C far zoom  not triggered",
            ),
        ]
        sheet = Image.new("RGB", (sum(panel.width for panel in panels), panels[0].height), (255, 255, 255))
        offset = 0
        for panel in panels:
            sheet.paste(panel, (offset, 0))
            offset += panel.width
        out = EVIDENCE_ROOT / f"{key}_compare.jpg"
        sheet.save(out, quality=90)
        print(f"evidence: {out}")


def probe_far(keys: list[str], model_name: str) -> None:
    """Separate diagnostic: test the fallback crop without changing C metrics."""
    load_env()
    manifest = json.loads((CROP_ROOT / "manifest.json").read_text(encoding="utf-8"))
    by_key = {sample["key"]: sample for sample in manifest["samples"]}
    out_dir = RUN_ROOT / "far_probe" / model_name
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        sample = by_key[key]
        far_image = ROOT / sample["far"]
        result = call_model(model_name, far_image, FAR_PROMPT)
        with Image.open(far_image) as opened:
            vehicles = normalize_vehicles(result.get("parsed"), opened.size)
        row = {
            "sample_id": key,
            "truth": sample["truth"],
            "far_image": str(far_image.relative_to(ROOT)),
            "far_vehicles": vehicles,
            "far_count": result_count(vehicles),
            **result,
        }
        (out_dir / f"{key}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  far probe {key:<14} count={row['far_count']} latency={result.get('latency_s')}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--run", choices=["A_full", "B_aisle", "C_adaptive"])
    parser.add_argument("--report", choices=["A_full", "B_aisle", "C_adaptive"])
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--evidence", action="store_true")
    parser.add_argument("--probe-far", action="store_true")
    parser.add_argument("--model", default="doubao", choices=sorted(MODELS))
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--keys")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tag")
    args = parser.parse_args()
    keys = [item.strip() for item in args.keys.split(",") if item.strip()] if args.keys else None
    if args.build:
        build()
    if args.run:
        run_config(args.run, args.model, args.workers, keys, args.force, args.tag)
    if args.report:
        report(args.report, args.model, tag=args.tag)
    if args.aggregate:
        aggregate(["A_full", "B_aisle", "C_adaptive"], args.model, [args.tag or "", "r2", "r3"])
    if args.evidence:
        build_evidence(keys or ["north_300", "north_5", "north_600", "south_2100"], args.model)
    if args.probe_far:
        probe_far(keys or ["north_5", "north_600"], args.model)


if __name__ == "__main__":
    main()
