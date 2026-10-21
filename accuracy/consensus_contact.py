"""Render the four baseline error frames with per-model count predictions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from consensus_evaluate import ALL_MODELS, CORE_MODELS, ERROR_FRAMES, ROOT, load_result, load_truth


LABELS = {
    "doubao": "Doubao",
    "aibox-deepseek-v4.1-flash": "DeepSeek v4.1 Flash",
    "aibox-glm-5.3-flash": "GLM 5.3 Flash",
    "zhipu": "Zhipu glm-4.5v",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"
    return ImageFont.truetype(path, size)


def fit_image(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def draw_count(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, value: int | None, gold: int) -> None:
    if value is None:
        text = f"{label}: 失败"
        color = (120, 120, 120)
    else:
        text = f"{label}: {value}"
        color = (20, 140, 70) if value == gold else (190, 50, 50)
    draw.text(xy, text, font=font(21), fill=color)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "accuracy" / "runs" / "consensus_v1")
    parser.add_argument(
        "--truth",
        type=Path,
        default=ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "accuracy" / "evidence" / "consensus_v1" / "errors_contact.jpg",
    )
    args = parser.parse_args()

    truth = load_truth(args.truth)
    records = {
        model: {
            path.stem: load_result(path)
            for path in sorted((args.runs / "raw" / model).glob("*.json"))
        }
        for model in ALL_MODELS
    }

    cell_w, cell_h = 740, 790
    header_h = 120
    footer_h = 90
    canvas = Image.new("RGB", (cell_w * 2, header_h + cell_h * 2 + footer_h), (247, 247, 243))
    draw = ImageDraw.Draw(canvas)
    draw.text((36, 24), "四错误帧 · 多模型预测对照", font=font(40, bold=True), fill=(25, 32, 40))
    draw.text(
        (38, 76),
        "按旧纯 aisle 基线定义的 4 个错误帧；同一 20 帧/提示词。绿=命中真值，红=错误。",
        font=font(19),
        fill=(75, 82, 90),
    )

    for index, sample in enumerate(ERROR_FRAMES):
        col, row = index % 2, index // 2
        x0 = col * cell_w
        y0 = header_h + row * cell_h
        draw.rounded_rectangle(
            (x0 + 12, y0 + 10, x0 + cell_w - 12, y0 + cell_h - 10),
            radius=14,
            fill="white",
            outline=(205, 210, 214),
            width=2,
        )
        draw.text((x0 + 28, y0 + 20), sample, font=font(28, bold=True), fill=(25, 32, 40))
        draw.text(
            (x0 + 250, y0 + 27),
            f"人工真值 {truth[sample]}",
            font=font(23, bold=True),
            fill=(28, 72, 150),
        )
        image = fit_image(ROOT / "accuracy" / "crops" / f"{sample}_aisle.jpg", (400, 720))
        canvas.paste(image, (x0 + 26, y0 + 58))
        draw.rectangle((x0 + 26, y0 + 58, x0 + 426, y0 + 778), outline=(225, 225, 225), width=1)

        tx, ty = x0 + 448, y0 + 78
        draw.text((tx, ty), "模型计数", font=font(20, bold=True), fill=(90, 90, 90))
        ty += 38
        for model in ALL_MODELS:
            record = records[model].get(sample)
            value = record.get("count") if record and record.get("ok") else None
            draw_count(draw, (tx, ty), LABELS[model], value, truth[sample])
            ty += 40

        votes = [
            records[model][sample]["count"]
            for model in CORE_MODELS
            if records[model].get(sample, {}).get("ok")
        ]
        freq = Counter(votes)
        if votes and freq.most_common(1)[0][1] >= 2:
            value = freq.most_common(1)[0][0]
            majority = f"2-of-3 多数票：{value}"
            majority_color = (20, 140, 70) if value == truth[sample] else (190, 50, 50)
        else:
            majority = "2-of-3 多数票：无多数"
            majority_color = (120, 120, 120)
        draw.text((tx, ty + 14), majority, font=font(21, bold=True), fill=majority_color)
        ty += 62
        draw.text((tx, ty), "原始回答与 bbox 见", font=font(17), fill=(110, 110, 110))
        ty += 25
        draw.text((tx, ty), "runs/consensus_v1/raw/", font=font(16), fill=(110, 110, 110))

    draw.text(
        (38, canvas.height - footer_h + 18),
        "注：本图只比较总数；本轮 Doubao 已在 north_300 报对，另新增 south_1800 错误。多数票正确不等于可上线。",
        font=font(19),
        fill=(75, 82, 90),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out, quality=92)
    print(f"contact sheet: {args.out}")


if __name__ == "__main__":
    main()
