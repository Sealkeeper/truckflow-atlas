"""Measure per-vehicle candidate-box coverage on two user-annotated frames.

This is a two-frame box-level diagnostic only. It is deliberately not folded
into the 20-frame count accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from consensus_evaluate import ALL_MODELS, ROOT, load_result


ANNOTATIONS = Path(r"D:\File\PROJECT\codex\codex-货车\codexcodex-货车\review\user-attachments-20261021")
CASES = [
    ("north_600", "1000_2.png", 4),
    ("north_5", "0005_1.png", 5),
]
LABELS = {
    "doubao": "Doubao",
    "aibox-deepseek-v4.1-flash": "DeepSeek v4.1 Flash",
    "aibox-glm-5.3-flash": "GLM 5.3 Flash",
    "zhipu": "Zhipu glm-4.5v",
}


def detect_red_boxes(path: Path) -> list[list[float]]:
    image = np.array(Image.open(path).convert("RGB"))
    r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    mask = (
        ((r.astype(np.int16) > 150) & (r.astype(np.int16) - g.astype(np.int16) > 70) & (r.astype(np.int16) - b.astype(np.int16) > 70))
        .astype(np.uint8)
        * 255
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # User boxes can touch at corners, so their outer red strokes merge. Use the
    # white interior holes instead: each hollow rectangle has its own hole.
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    height, width = image.shape[:2]
    boxes = []
    for index, contour in enumerate(contours):
        if hierarchy is None or hierarchy[0][index][3] == -1:
            continue
        if cv2.contourArea(contour) < 250:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.03 or h < height * 0.03:
            continue
        if w * h > 0.35 * width * height:
            continue
        pad = 2
        boxes.append(
            [
                max(0, x - pad) / width,
                max(0, y - pad) / height,
                min(width, x + w + pad) / width,
                min(height, y + h + pad) / height,
            ]
        )
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def model_boxes(runs: Path, model: str, sample: str, coordinate_mode: str = "letterbox") -> list[list[float]]:
    path = runs / "raw" / model / f"{sample}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    vehicles = (payload.get("parsed") or {}).get("vehicles") or []
    boxes = []
    for vehicle in vehicles:
        box = vehicle.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            continue
        values = [float(value) for value in box]
        pixel_coords = max(values) > 1.5
        if max(values) > 1.5:
            values = [values[0] / 1040, values[1] / 1920, values[2] / 1040, values[3] / 1920]
        if coordinate_mode == "letterbox" and not pixel_coords:
            # The 1040x1920 portrait crop is letterboxed into a square input:
            # content width fraction = 1040/1920, side padding = 0.22917.
            content = 1040 / 1920
            offset = (1 - content) / 2
            values = [
                (values[0] - offset) / content,
                values[1],
                (values[2] - offset) / content,
                values[3],
            ]
        x0, y0, x1, y1 = values
        x0, x1 = max(0.0, min(x0, x1)), min(1.0, max(x0, x1))
        y0, y1 = max(0.0, min(y0, y1)), min(1.0, max(y0, y1))
        boxes.append([x0, y0, x1, y1])
    return boxes


def overlap(gold: list[float], candidate: list[float]) -> tuple[float, float]:
    gx0, gy0, gx1, gy1 = gold
    cx0, cy0, cx1, cy1 = candidate
    ix0, iy0 = max(gx0, cx0), max(gy0, cy0)
    ix1, iy1 = min(gx1, cx1), min(gy1, cy1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0, 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    gold_area = max(1e-9, (gx1 - gx0) * (gy1 - gy0))
    cand_area = max(1e-9, (cx1 - cx0) * (cy1 - cy0))
    union = gold_area + cand_area - inter
    return inter / union, inter / gold_area


def covers(gold: list[float], candidate: list[float]) -> bool:
    iou, inter_over_gold = overlap(gold, candidate)
    cx = (gold[0] + gold[2]) / 2
    cy = (gold[1] + gold[3]) / 2
    center_inside = candidate[0] <= cx <= candidate[2] and candidate[1] <= cy <= candidate[3]
    return center_inside or iou >= 0.25 or inter_over_gold >= 0.5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "accuracy" / "runs" / "consensus_v1")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "accuracy" / "runs" / "consensus_v1" / "coverage_2frames.json",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        default=ROOT / "accuracy" / "evidence" / "consensus_v1" / "coverage_2frames.jpg",
    )
    parser.add_argument("--coordinate-mode", choices=["letterbox", "identity"], default="letterbox")
    args = parser.parse_args()

    report: dict[str, object] = {
        "schema": "truckflow-consensus-coverage-2frames-v1",
        "annotation_source": str(ANNOTATIONS / "manifest.json"),
        "scope": "diagnostic on 2 user-annotated frames only; not 20-frame accuracy",
        "coordinate_mode": (
            "normalized bbox x de-letterboxed from square input: "
            "x_crop=(x_model-0.22917)/(1040/1920)"
            if args.coordinate_mode == "letterbox"
            else "identity"
        ),
        "frames": {},
        "per_model": {},
    }
    per_model = {
        model: {"covered": 0, "marked": 0, "frames": {}, "candidate_boxes": 0}
        for model in ALL_MODELS
    }
    detected_by_case: dict[str, list[list[float]]] = {}
    for sample, filename, expected in CASES:
        boxes = detect_red_boxes(ANNOTATIONS / filename)
        if len(boxes) != expected:
            raise SystemExit(f"{filename}: detected {len(boxes)} red boxes, expected {expected}: {boxes}")
        detected_by_case[sample] = boxes
        frame_report = {"file": filename, "marked": expected, "user_boxes": boxes, "models": {}}
        for model in ALL_MODELS:
            candidates = model_boxes(args.runs, model, sample, args.coordinate_mode)
            hits = []
            for index, gold in enumerate(boxes):
                best_iou = max((overlap(gold, candidate)[0] for candidate in candidates), default=0.0)
                hit = any(covers(gold, candidate) for candidate in candidates)
                hits.append({"vehicle": index + 1, "covered": hit, "best_iou": round(best_iou, 3)})
            covered = sum(item["covered"] for item in hits)
            per_model[model]["covered"] += covered
            per_model[model]["marked"] += expected
            per_model[model]["candidate_boxes"] += len(candidates)
            per_model[model]["frames"][sample] = {
                "covered": covered,
                "marked": expected,
                "candidate_boxes": len(candidates),
                "vehicles": hits,
            }
            frame_report["models"][model] = {
                "covered": covered,
                "marked": expected,
                "candidate_boxes": len(candidates),
                "vehicles": hits,
            }
        report["frames"][sample] = frame_report

    for model, item in per_model.items():
        report["per_model"][model] = {**item, "recall": round(item["covered"] / item["marked"] * 100, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Overlay: two rows (frames) x four columns (models), user boxes in red,
    # model boxes in green, with the per-frame coverage shown under each image.
    cell = (320, 590)
    header = 100
    canvas = Image.new("RGB", (cell[0] * 4, header + cell[1] * 2), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    bold_path = r"C:\Windows\Fonts\msyhbd.ttc"
    draw.text((24, 18), "逐车覆盖诊断（仅 2 帧，不计入 20 帧准确率）", font=ImageFont.truetype(bold_path, 32), fill=(25, 32, 40))
    draw.text((26, 62), "红框=用户逐车标注；绿框=模型候选框；统计口径为中心点/ IoU 覆盖。", font=ImageFont.truetype(font_path, 18), fill=(80, 85, 92))
    for row, (sample, filename, expected) in enumerate(CASES):
        original = Image.open(ANNOTATIONS / filename).convert("RGB")
        original.thumbnail(cell, Image.Resampling.LANCZOS)
        for col, model in enumerate(ALL_MODELS):
            candidates = model_boxes(args.runs, model, sample, args.coordinate_mode)
            panel = original.copy()
            panel_draw = ImageDraw.Draw(panel)
            width, height = panel.size
            for box in detected_by_case[sample]:
                panel_draw.rectangle(
                    (box[0] * width, box[1] * height, box[2] * width, box[3] * height),
                    outline=(255, 30, 30),
                    width=3,
                )
            for box in candidates:
                panel_draw.rectangle(
                    (box[0] * width, box[1] * height, box[2] * width, box[3] * height),
                    outline=(20, 200, 80),
                    width=2,
                )
            x = col * cell[0]
            y = header + row * cell[1]
            draw.text((x + 10, y + 4), f"{sample} · {LABELS[model]}", font=ImageFont.truetype(bold_path, 18), fill=(25, 32, 40))
            canvas.paste(panel, (x + (cell[0] - width) // 2, y + 30))
            frame = per_model[model]["frames"][sample]
            draw.text(
                (x + 10, y + cell[1] - 40),
                f"覆盖 {frame['covered']}/{frame['marked']} · 候选框 {frame['candidate_boxes']}",
                font=ImageFont.truetype(font_path, 18),
                fill=(20, 140, 70) if frame["covered"] == frame["marked"] else (190, 50, 50),
            )
    args.overlay.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.overlay, quality=92)
    print(json.dumps(report["per_model"], ensure_ascii=False, indent=2))
    print(f"coverage: {args.out}")
    print(f"overlay: {args.overlay}")


if __name__ == "__main__":
    main()
