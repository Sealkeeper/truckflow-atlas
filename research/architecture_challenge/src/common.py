"""Shared experiment utilities.

This module deliberately contains no object detector and no tracker. Geometry is
used only to create crops, map candidate boxes between crops, and propose pairs
for semantic adjudication by a multimodal model.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import requests
from PIL import Image, ImageDraw, ImageFont


RESEARCH = Path(__file__).resolve().parents[1]
REPO = RESEARCH.parents[1]
PUBLIC = Path(
    os.environ.get("TRUCKFLOW_PUBLIC", str(REPO.parents[1] / "all-sessions-can-see"))
)
FRAMES = REPO / "assets" / "frames"
GOLD_PATH = PUBLIC / "data" / "gold" / "camera_counts_v0.json"
EVIDENCE = RESEARCH / "evidence"
RUNS = RESEARCH / "runs"
REPORTS = RESEARCH / "reports"

MODELS: dict[str, dict[str, str]] = {
    "doubao": {
        "base": "DOUBAO_BASE_URL",
        "key": "DOUBAO_API_KEY",
        "model": "DOUBAO_MODEL",
    },
    "zhipu": {
        "base": "ZHIPU_BASE_URL",
        "key": "ZHIPU_API_KEY",
        "model": "ZHIPU_MODEL",
    },
    "aibox": {
        "base": "AIBOX_BASE_URL",
        "key": "AIBOX_API_KEY",
        "model": "AIBOX_MODEL",
    },
}


def load_env() -> None:
    """Load local API configuration without printing secrets."""
    for path in (REPO / ".env", PUBLIC / ".env"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def data_uri(image: Path) -> str:
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    payload = base64.b64encode(image.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


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
    prompt: str,
    images: Sequence[Path],
    *,
    model: str = "doubao",
    stage: str = "",
    max_tokens: int = 2400,
    temperature: float = 0,
    retries: int = 2,
    deadline_s: float = 150.0,
) -> dict[str, Any]:
    """Call one multimodal model and retain the full response as evidence."""
    load_env()
    cfg = MODELS.get(model)
    if cfg is None:
        raise ValueError(f"unknown model: {model}")
    api_key = os.environ.get(cfg["key"], "")
    base = os.environ.get(cfg["base"], "").rstrip("/")
    model_id = os.environ.get(cfg["model"], "")
    record: dict[str, Any] = {
        "stage": stage,
        "model": model,
        "model_id": model_id,
        "prompt": prompt,
        "images": [str(p) for p in images],
        "requested_max_tokens": max_tokens,
        "temperature": temperature,
    }
    if not api_key or not base or not model_id:
        record.update(ok=False, error="missing model configuration")
        return record

    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": data_uri(p)}} for p in images
    ]
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": model_id,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }

    started = time.perf_counter()
    last_error = ""
    for attempt in range(retries):
        try:
            with requests.post(
                base + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=(15, 60),
                stream=True,
            ) as response:
                status = response.status_code
                if status in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                    last_error = f"HTTP {status}: {response.text[:400]}"
                    time.sleep(3 * (attempt + 1))
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                read_started = time.monotonic()
                for chunk in response.iter_content(32768):
                    chunks.append(chunk)
                    if time.monotonic() - read_started > deadline_s:
                        raise TimeoutError(
                            f"response exceeded {deadline_s:.0f}s wall-clock deadline"
                        )
                body = json.loads(b"".join(chunks))
            message = body.get("choices", [{}])[0].get("message", {})
            raw = message.get("content", "")
            if isinstance(raw, list):
                raw = "".join(
                    part.get("text", "") for part in raw if isinstance(part, dict)
                )
            reasoning = message.get("reasoning_content", "")
            record.update(
                ok=True,
                latency_s=round(time.perf_counter() - started, 2),
                usage=body.get("usage"),
                raw_text=raw,
                reasoning_text=reasoning,
                finish_reason=body.get("choices", [{}])[0].get("finish_reason"),
            )
            try:
                record["parsed"] = extract_json(raw)
            except Exception as exc:
                record["parse_error"] = f"{type(exc).__name__}: {exc}"
            return record
        except Exception as exc:  # keep failure text for the route report
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < retries:
                time.sleep(3 * (attempt + 1))
    record.update(
        ok=False,
        latency_s=round(time.perf_counter() - started, 2),
        error=last_error,
    )
    return record


def bbox_array(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    box = [min(1.0, max(0.0, v)) for v in box]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def bbox_center(box: Sequence[float]) -> list[float]:
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def bbox_area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def intersection_over_smaller(a: Sequence[float], b: Sequence[float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    smaller = min(bbox_area(a), bbox_area(b))
    return inter / smaller if smaller > 0 else 0.0


def union_bbox(boxes: Iterable[Sequence[float]]) -> list[float]:
    boxes = list(boxes)
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _resize_long(image: Image.Image, long_side: int) -> Image.Image:
    width, height = image.size
    scale = long_side / max(width, height)
    if abs(scale - 1.0) < 0.02:
        return image
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def save_crop(
    source: Path,
    bbox: Sequence[float],
    out: Path,
    *,
    pad: float = 0.0,
    long_side: int = 1500,
    grid: bool = True,
    border: bool = True,
) -> dict[str, Any]:
    """Crop a normalized box, upscale it, and optionally add a coordinate grid."""
    image = Image.open(source).convert("RGB")
    width, height = image.size
    x0 = max(0.0, bbox[0] - pad)
    y0 = max(0.0, bbox[1] - pad)
    x1 = min(1.0, bbox[2] + pad)
    y1 = min(1.0, bbox[3] + pad)
    pixels = (
        round(x0 * width),
        round(y0 * height),
        round(x1 * width),
        round(y1 * height),
    )
    crop = image.crop(pixels)
    crop = _resize_long(crop, long_side)
    draw = ImageDraw.Draw(crop, "RGBA")
    cw, ch = crop.size
    if grid:
        font = _font(max(11, min(18, cw // 55)))
        for step in range(1, 10):
            x = cw * step / 10
            y = ch * step / 10
            draw.line([(x, 0), (x, ch)], fill=(255, 0, 190, 70), width=2)
            draw.line([(0, y), (cw, y)], fill=(0, 255, 210, 70), width=2)
        for step in range(1, 10):
            x = cw * step / 10
            y = ch * step / 10
            draw.text((x + 4, 4), f"{step / 10:.1f}", fill=(255, 255, 255, 230), font=font)
            draw.text((4, y + 2), f"{step / 10:.1f}", fill=(255, 255, 255, 230), font=font)
    if border:
        draw.rectangle([0, 0, cw - 1, ch - 1], outline=(255, 210, 0, 255), width=4)
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, quality=92)
    return {
        "source": str(source),
        "bbox": [x0, y0, x1, y1],
        "out": str(out),
        "size": [cw, ch],
    }


def annotation_image(
    source: Path,
    candidates: Sequence[dict[str, Any]],
    out: Path,
    *,
    long_side: int = 1600,
) -> dict[str, Any]:
    """Render numbered candidate boxes back into the frame for adversarial review."""
    image = Image.open(source).convert("RGB")
    image = _resize_long(image, long_side)
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(max(18, min(30, width // 45)))
    palette = [
        (255, 40, 40, 255),
        (0, 210, 255, 255),
        (255, 220, 0, 255),
        (80, 255, 120, 255),
        (255, 90, 220, 255),
        (255, 150, 40, 255),
        (120, 140, 255, 255),
        (0, 255, 200, 255),
    ]
    rendered: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        box = candidate["bbox_global"]
        color = palette[(index - 1) % len(palette)]
        pixels = [box[0] * width, box[1] * height, box[2] * width, box[3] * height]
        draw.rectangle(pixels, outline=color, width=6)
        label = str(index)
        tw = draw.textlength(label, font=font)
        tx = max(2, min(width - tw - 8, pixels[0]))
        ty = max(2, pixels[1] - 34)
        draw.rectangle([tx - 3, ty - 2, tx + tw + 8, ty + 30], fill=(0, 0, 0, 190))
        draw.text((tx + 2, ty), label, fill=color, font=font)
        rendered.append({"id": index, "bbox_px": pixels, "size": candidate.get("size")})
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, quality=92)
    return {"out": str(out), "size": [width, height], "rendered": rendered}


def side_by_side(
    source: Path,
    crop_a: Sequence[float],
    crop_b: Sequence[float],
    out: Path,
    *,
    labels: tuple[str, str] = ("A", "B"),
    panel: int = 760,
) -> dict[str, Any]:
    """Build an A/B evidence image for a same-vehicle adjudication call."""
    image = Image.open(source).convert("RGB")
    width, height = image.size
    panels: list[Image.Image] = []
    for box in (crop_a, crop_b):
        x0, y0 = max(0.0, box[0] - 0.02), max(0.0, box[1] - 0.02)
        x1, y1 = min(1.0, box[2] + 0.02), min(1.0, box[3] + 0.02)
        pixels = (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))
        crop = image.crop(pixels)
        crop.thumbnail((panel, panel), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (panel, panel), (18, 18, 18))
        canvas.paste(crop, ((panel - crop.width) // 2, (panel - crop.height) // 2))
        panels.append(canvas)

    combined = Image.new("RGB", (panel * 2 + 12, panel + 44), (10, 10, 10))
    combined.paste(panels[0], (0, 40))
    combined.paste(panels[1], (panel + 12, 40))
    draw = ImageDraw.Draw(combined)
    font = _font(34)
    draw.text((panel // 2 - 10, 4), labels[0], fill=(255, 220, 40), font=font)
    draw.text((panel + 12 + panel // 2 - 10, 4), labels[1], fill=(80, 220, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.save(out, quality=92)
    return {"out": str(out), "size": list(combined.size)}


def adjudication_context_image(
    source: Path,
    box_a: Sequence[float],
    box_b: Sequence[float],
    out: Path,
    *,
    canvas: tuple[int, int] = (1600, 900),
) -> dict[str, Any]:
    """Full-frame context plus two zooms, so cab/trailer splits are visible.

    Geometry only draws evidence. The same/different decision remains a
    multimodal model judgment.
    """
    image = Image.open(source).convert("RGB")
    width, height = image.size
    cw, ch = canvas
    result = Image.new("RGB", canvas, (12, 12, 12))
    draw = ImageDraw.Draw(result)

    context_w, context_h = cw - 760, ch - 90
    scale = min(context_w / width, context_h / height)
    frame = image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )
    fx, fy = 14, 64
    result.paste(frame, (fx, fy))
    fw, fh = frame.size

    def box_px(box: Sequence[float]) -> list[float]:
        return [fx + box[0] * fw, fy + box[1] * fh, fx + box[2] * fw, fy + box[3] * fh]

    for box, color, label in (
        (box_a, (255, 220, 20, 255), "A"),
        (box_b, (30, 230, 255, 255), "B"),
    ):
        pixels = box_px(box)
        draw.rectangle(pixels, outline=color, width=5)
        font = _font(28)
        draw.text((pixels[0] + 3, max(50, pixels[1] - 32)), label, fill=color, font=font)

    panel = 320
    for index, (box, color, label, top) in enumerate(
        ((box_a, (255, 220, 20, 255), "A", 64), (box_b, (30, 230, 255, 255), "B", 64 + panel + 36))
    ):
        # Keep the zoom close to the proposed box. Padding used to pull
        # neighbouring trucks into each panel, which caused a correctly
        # overlapping pair to be judged as different vehicles.
        x0, y0 = max(0.0, box[0] - 0.004), max(0.0, box[1] - 0.004)
        x1, y1 = min(1.0, box[2] + 0.004), min(1.0, box[3] + 0.004)
        crop = image.crop(
            (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))
        )
        crop.thumbnail((panel, panel), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (panel, panel), (24, 24, 24))
        tile.paste(crop, ((panel - crop.width) // 2, (panel - crop.height) // 2))
        tx, ty = cw - panel - 26, top + 30
        result.paste(tile, (tx, ty))
        draw.rectangle([tx, ty, tx + panel - 1, ty + panel - 1], outline=color, width=4)
        draw.text((tx + 4, ty - 34), f"{label} 放大", fill=color, font=_font(24))

    draw.text(
        (14, 12),
        "左图：整帧上下文（黄框 A / 青框 B）    右图：A、B 局部放大",
        fill=(235, 235, 235),
        font=_font(26),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out, quality=92)
    return {"out": str(out), "size": list(result.size)}


def canonical_counts(vehicles: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(vehicles), "large": 0, "medium": 0, "small": 0, "unknown": 0}
    for vehicle in vehicles:
        size = vehicle.get("size", "unknown")
        if size not in ("large", "medium", "small"):
            size = "unknown"
        counts[size] += 1
    return counts


def score(gold: dict[str, Any], predicted: dict[str, int]) -> dict[str, Any]:
    gold_counts = {
        "total": int(gold["total"]),
        "large": int(gold.get("large", 0)),
        "medium": int(gold.get("medium", 0)),
        "small": int(gold.get("small", 0)),
        "unknown": 0,
    }
    count_error = predicted["total"] - gold_counts["total"]
    class_l1 = sum(abs(predicted[k] - gold_counts[k]) for k in ("large", "medium", "small"))
    exact = (
        count_error == 0
        and all(predicted[k] == gold_counts[k] for k in ("large", "medium", "small"))
        and predicted["unknown"] == 0
    )
    return {
        "gold": gold_counts,
        "predicted": predicted,
        "count_error": count_error,
        "miss": max(0, -count_error),
        "extra": max(0, count_error),
        "class_l1": class_l1,
        "type_swaps_lower_bound": max(0, (class_l1 - abs(count_error)) // 2),
        "unknown": predicted["unknown"],
        "exact": exact,
    }


def load_gold() -> dict[tuple[str, int], dict[str, Any]]:
    payload = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    return {(row["camera"], int(row["time"])): row for row in payload["samples"]}


def frame_path(camera: str, time_s: int) -> Path:
    return FRAMES / f"{camera}_{time_s}.jpg"


def relative(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def usage_total(record: dict[str, Any]) -> dict[str, int]:
    usage = record.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def sum_calls(calls: Iterable[dict[str, Any]]) -> dict[str, Any]:
    calls = list(calls)
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    latency = 0.0
    for call in calls:
        for key, value in usage_total(call).items():
            tokens[key] += value
        latency += float(call.get("latency_s") or 0)
    return {
        "calls": len(calls),
        "failed_calls": sum(1 for c in calls if not c.get("ok")),
        "latency_s": round(latency, 2),
        **tokens,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def strip_none(value: Any) -> Any:
    """Remove huge/irrelevant null fields before persisting evidence."""
    if isinstance(value, dict):
        return {k: strip_none(v) for k, v in value.items() if v not in (None, "")}
    if isinstance(value, list):
        return [strip_none(v) for v in value]
    return value
