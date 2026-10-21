"""Build candidate crops and comparison sheets from crop-model proposals.

Cross-model geometric merging is only used to avoid asking about near-identical
boxes repeatedly. It never decides physical identity or vehicle type.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from extract_frames import LANE_BOX, OBSERVATIONS, font
from model_client import ROOT


GEO_WINDOWS = {
    "top": [0.35, 0.02, 0.62, 0.19],
    "bottom": [0.30, 0.82, 0.75, 1.0],
    "bottom_right": [0.55, 0.78, 0.90, 1.0],
}


def iou(a: list[float], b: list[float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(1e-9, area_a + area_b - inter)


def center(box: list[float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def close_enough(a: list[float], b: list[float]) -> bool:
    if iou(a, b) >= 0.46:
        return True
    ca, cb = center(a), center(b)
    distance = math.dist(ca, cb)
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    ratio = min(area_a, area_b) / max(area_a, area_b)
    return distance < 0.025 and ratio > 0.55


def normalise_box(raw: Any, crop_size: tuple[int, int]) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        box = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if max(box) > 1.5:
        width, height = crop_size
        box = [box[0] / width, box[1] / height, box[2] / width, box[3] / height]
    box = [max(0.0, min(1.0, value)) for value in box]
    if box[2] - box[0] < 0.01 or box[3] - box[1] < 0.01:
        return None
    return box


def crop_to_original(box: list[float], camera: str) -> list[float]:
    x0, y0, x1, y1 = LANE_BOX[camera]
    width, height = x1 - x0, y1 - y0
    return [
        (x0 + box[0] * width) / 1280,
        (y0 + box[1] * height) / 960,
        (x0 + box[2] * width) / 1280,
        (y0 + box[3] * height) / 960,
    ]


def collect(observation: str, camera: str) -> list[dict[str, Any]]:
    crop_path = ROOT / "assets" / "crops" / f"{camera}_t{observation.split('_')[1]}_lane.jpg"
    with Image.open(crop_path) as image:
        crop_size = image.size
    whole_path = ROOT / "assets" / "frames" / f"{camera}_t{observation.split('_')[1]}.jpg"
    with Image.open(whole_path) as image:
        whole_size = image.size
    proposals: list[dict[str, Any]] = []
    for mode in ("crop", "whole"):
        for path in sorted((ROOT / "data" / "runs" / "primary").glob(f"{observation}_{mode}__*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            run = payload["run"]
            if not run.get("ok"):
                continue
            for vehicle in run.get("parsed", {}).get("vehicles", []):
                if mode == "crop":
                    box = normalise_box(vehicle.get("bbox"), crop_size)
                    original_box = crop_to_original(box, camera) if box is not None else None
                else:
                    original_box = normalise_box(vehicle.get("bbox"), whole_size)
                if original_box is None:
                    continue
                proposals.append(
                    {
                        "model": run["model"],
                        "source_mode": mode,
                        "bbox": original_box,
                        "model_size": vehicle.get("size", "unknown"),
                        "visible": vehicle.get("visible"),
                        "uncertain": bool(vehicle.get("uncertain")),
                        "identity_clues": vehicle.get("identity_clues", ""),
                    }
                )

    groups: list[dict[str, Any]] = []
    for proposal in proposals:
        for group in groups:
            if close_enough(proposal["bbox"], group["bbox"]):
                group["proposals"].append(proposal)
                group["models"].append(f"{proposal['model']}/{proposal['source_mode']}")
                # Keep the union, which preserves the full vehicle when one model
                # returned only its cargo section.
                group["bbox"] = [
                    min(group["bbox"][0], proposal["bbox"][0]),
                    min(group["bbox"][1], proposal["bbox"][1]),
                    max(group["bbox"][2], proposal["bbox"][2]),
                    max(group["bbox"][3], proposal["bbox"][3]),
                ]
                break
        else:
            groups.append(
                {
                    "bbox": proposal["bbox"],
                    "models": [f"{proposal['model']}/{proposal['source_mode']}"],
                    "proposals": [proposal],
                }
            )
    for name, window in GEO_WINDOWS.items():
        covered_area = 0.0
        window_area = (window[2] - window[0]) * (window[3] - window[1])
        for group in groups:
            box = group["bbox"]
            ix0, iy0 = max(window[0], box[0]), max(window[1], box[1])
            ix1, iy1 = min(window[2], box[2]), min(window[3], box[3])
            covered_area += max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if covered_area / max(window_area, 1e-9) < 0.55:
            groups.append(
                {
                    "geo_window": name,
                    "bbox": window.copy(),
                    "models": ["geometry"],
                    "proposals": [],
                }
            )
    groups.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    prefix = "N" if camera == "north" else "S"
    for index, group in enumerate(groups, 1):
        group["candidate"] = f"{prefix}{index}"
        group["models"] = sorted(set(group["models"]))
    return groups


def padded_crop(image: Image.Image, bbox: list[float]) -> Image.Image:
    width, height = image.size
    x0, y0, x1, y1 = bbox
    pad_x = max(0.012, (x1 - x0) * 0.08)
    pad_y = max(0.012, (y1 - y0) * 0.05)
    pixels = (
        max(0, round((x0 - pad_x) * width)),
        max(0, round((y0 - pad_y) * height)),
        min(width, round((x1 + pad_x) * width)),
        min(height, round((y1 + pad_y) * height)),
    )
    return image.crop(pixels)


def candidate_sheet(observation: str, camera: str, groups: list[dict[str, Any]]) -> Path:
    frame_path = ROOT / "assets" / "frames" / f"{camera}_t{observation.split('_')[1]}.jpg"
    cols = 4
    panel_w, panel_h, label_h = 300, 270, 48
    rows = max(1, math.ceil(len(groups) / cols))
    header_h = 510
    sheet = Image.new("RGB", (cols * panel_w, header_h + rows * (panel_h + label_h)), "#081018")
    draw = ImageDraw.Draw(sheet)
    with Image.open(frame_path).convert("RGB") as frame:
        overview = ImageOps.contain(frame, (650, 470), Image.Resampling.LANCZOS)
        sheet.paste(overview, (15, 20))
        scale_x, scale_y = overview.width / frame.width, overview.height / frame.height
        for group in groups:
            x0, y0, x1, y1 = group["bbox"]
            rectangle = (
                15 + round(x0 * frame.width * scale_x),
                20 + round(y0 * frame.height * scale_y),
                15 + round(x1 * frame.width * scale_x),
                20 + round(y1 * frame.height * scale_y),
            )
            draw.rectangle(rectangle, outline="#ffcf5c", width=3)
            draw.text((rectangle[0] + 3, rectangle[1] + 2), group["candidate"], fill="#ffffff", font=font(21, True))
        draw.text(
            (690, 26),
            "SAME SOURCE FRAME\nOVERLAPPING WINDOWS\nCount each physical truck once.",
            fill="#63f5d7",
            font=font(23, True),
        )
        for index, group in enumerate(groups):
            crop = padded_crop(frame, group["bbox"])
            crop = ImageOps.contain(crop, (panel_w - 20, panel_h - 12), Image.Resampling.LANCZOS)
            column, row = index % cols, index // cols
            left = column * panel_w + (panel_w - crop.width) // 2
            top = header_h + row * (panel_h + label_h) + label_h + (panel_h - crop.height) // 2
            sheet.paste(crop, (left, top))
            compact = {
                f"{model.split('/')[0][0].upper()}/{model.split('/')[1][0]}"
                for model in group["models"]
                if model != "geometry"
            }
            text = f"{group['candidate']}  {' '.join(sorted(compact)) or 'GEO'}"
            draw.text(
                (column * panel_w + 12, header_h + row * (panel_h + label_h) + 13),
                text,
                fill="#55f4d4",
                font=font(18, True),
            )
            draw.rectangle(
                (
                    column * panel_w + 3,
                    header_h + row * (panel_h + label_h) + 3,
                    (column + 1) * panel_w - 4,
                    header_h + (row + 1) * (panel_h + label_h) - 4,
                ),
                outline="#415267",
                width=2,
            )
            crop_dir = ROOT / "assets" / "candidates"
            crop_dir.mkdir(parents=True, exist_ok=True)
            padded_crop(frame, group["bbox"]).save(
                crop_dir / f"{observation}_{group['candidate']}.jpg", quality=94, subsampling=0
            )
    output = ROOT / "assets" / "sheets" / f"{observation}_candidates.jpg"
    sheet.save(output, quality=94, subsampling=0)
    return output


def pair_sheet(time_s: int, north: list[dict[str, Any]], south: list[dict[str, Any]]) -> Path:
    columns = max(len(north), len(south))
    panel_w, panel_h, label_h = 280, 260, 50
    sheet = Image.new("RGB", (columns * panel_w, 2 * (panel_h + label_h)), "#081018")
    draw = ImageDraw.Draw(sheet)
    for row, (camera, groups) in enumerate((("north", north), ("south", south))):
        frame_path = ROOT / "assets" / "frames" / f"{camera}_t{time_s}.jpg"
        with Image.open(frame_path).convert("RGB") as frame:
            for index, group in enumerate(groups):
                crop = padded_crop(frame, group["bbox"])
                crop = ImageOps.contain(crop, (panel_w - 18, panel_h - 10), Image.Resampling.LANCZOS)
                left = index * panel_w + (panel_w - crop.width) // 2
                top = row * (panel_h + label_h) + label_h + (panel_h - crop.height) // 2
                sheet.paste(crop, (left, top))
                draw.text(
                    (index * panel_w + 12, row * (panel_h + label_h) + 10),
                    f"{group['candidate']}  {camera.upper()}",
                    fill="#55f4d4",
                    font=font(22, True),
                )
                draw.rectangle(
                    (
                        index * panel_w + 3,
                        row * (panel_h + label_h) + 3,
                        (index + 1) * panel_w - 4,
                        (row + 1) * (panel_h + label_h) - 4,
                    ),
                    outline="#415267",
                    width=2,
                )
    output = ROOT / "assets" / "sheets" / f"pairs_{time_s}.jpg"
    sheet.save(output, quality=94, subsampling=0)
    return output


def main() -> None:
    all_groups: dict[str, list[dict[str, Any]]] = {}
    for camera, times in OBSERVATIONS.items():
        for time_s in times:
            observation = f"{camera}_{time_s}"
            groups = collect(observation, camera)
            all_groups[observation] = groups
            candidate_sheet(observation, camera, groups)
            print(f"{observation}: {len(groups)} geometric candidates -> {[g['candidate'] for g in groups]}")

    for time_s in (600, 1200):
        a, b = f"north_{time_s}", f"south_{time_s}"
        if a in all_groups and b in all_groups:
            pair_sheet(time_s, all_groups[a], all_groups[b])
            print(f"pairs_{time_s}: {len(all_groups[a])} north x {len(all_groups[b])} south")

    output = ROOT / "data" / "candidates.json"
    output.write_text(json.dumps(all_groups, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
