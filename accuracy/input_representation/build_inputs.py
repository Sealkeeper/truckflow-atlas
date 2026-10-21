"""Build the frozen single-call multi-scale inputs.

Global view: the existing clean aisle crop (1040x1920).
Detail view: one fixed far-channel window (280x560 source pixels), scaled 2x.

The detail window is identical for every north/south sample. It is not tuned
per error frame and no generated content is added.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "assets" / "frames"
GLOBAL_CROPS = ROOT / "accuracy" / "crops"
OUT = ROOT / "accuracy" / "crops" / "multiscale_v1"
EVIDENCE = ROOT / "accuracy" / "evidence" / "input_representation"

# Frozen source-frame geometry. The existing aisle crop is documented in
# accuracy/runs/aisle_clean/_provenance.json.
GLOBAL_SOURCE = (350, 0, 870, 960)
GLOBAL_SCALE = 2
DETAIL_SOURCE = (480, 60, 760, 620)
DETAIL_SCALE = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def samples() -> list[str]:
    result = []
    for path in sorted(GLOBAL_CROPS.glob("*_aisle.jpg")):
        if "grid_aisle" in path.name:
            continue
        result.append(path.stem.removesuffix("_aisle"))
    return result


def font(size: int, bold: bool = False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def make_detail(frame: Image.Image) -> Image.Image:
    x0, y0, x1, y1 = DETAIL_SOURCE
    crop = frame.crop((x0, y0, x1, y1))
    return crop.resize(
        ((x1 - x0) * DETAIL_SCALE, (y1 - y0) * DETAIL_SCALE),
        Image.Resampling.LANCZOS,
    )


def build_layout_check(ids: list[str], out: Path) -> None:
    thumb_w, thumb_h = 360, 270
    cols, rows = 4, 5
    canvas = Image.new("RGB", (thumb_w * cols, (thumb_h + 34) * rows + 76), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 14), "20 帧固定几何检查：蓝=aisle 全局，绿=固定远景细节", font=font(28, True), fill=(25, 32, 40))
    draw.text((20, 50), "细节窗口 source x=480..760, y=60..620；2x Lanczos，无生成式补全", font=font(17), fill=(80, 85, 92))
    for index, sample in enumerate(ids):
        col, row = index % cols, index // cols
        x, y = col * thumb_w, 76 + row * (thumb_h + 34)
        frame = Image.open(FRAMES / f"{sample}.jpg").convert("RGB")
        frame.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (thumb_w, thumb_h), "white")
        panel.paste(frame, ((thumb_w - frame.width) // 2, (thumb_h - frame.height) // 2))
        sx = thumb_w / 1280
        sy = thumb_h / 960
        pd = ImageDraw.Draw(panel)
        pd.rectangle(
            (GLOBAL_SOURCE[0] * sx, GLOBAL_SOURCE[1] * sy, GLOBAL_SOURCE[2] * sx, GLOBAL_SOURCE[3] * sy),
            outline=(30, 110, 230),
            width=2,
        )
        pd.rectangle(
            (DETAIL_SOURCE[0] * sx, DETAIL_SOURCE[1] * sy, DETAIL_SOURCE[2] * sx, DETAIL_SOURCE[3] * sy),
            outline=(20, 170, 70),
            width=3,
        )
        canvas.paste(panel, (x, y))
        draw.text((x + 4, y + thumb_h + 4), sample, font=font(17), fill=(25, 32, 40))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=92)


def build_detail_contact(ids: list[str], out: Path) -> None:
    panel_w, panel_h = 280, 560
    cols, rows = 5, 4
    canvas = Image.new("RGB", (panel_w * cols, (panel_h + 34) * rows + 60), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((16, 12), "固定远景细节图 · 20 帧", font=font(28, True), fill=(25, 32, 40))
    draw.text((18, 46), "同一 source 窗口，仅做 2x Lanczos 缩放", font=font(17), fill=(80, 85, 92))
    for index, sample in enumerate(ids):
        col, row = index % cols, index // cols
        x, y = col * panel_w, 60 + row * (panel_h + 34)
        detail = Image.open(OUT / "detail" / f"{sample}.jpg").convert("RGB")
        detail.thumbnail((panel_w, panel_h), Image.Resampling.LANCZOS)
        canvas.paste(detail, (x, y))
        draw.text((x + 4, y + panel_h + 4), sample, font=font(17), fill=(25, 32, 40))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "detail").mkdir(exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    ids = samples()
    if len(ids) != 20:
        raise SystemExit(f"expected 20 aisle samples, found {len(ids)}")

    manifest = {
        "schema": "truckflow-multiscale-inputs-v1",
        "created_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "sample_count": len(ids),
        "samples": ids,
        "global_view": {
            "kind": "existing clean aisle crop",
            "source_frame_size": [1280, 960],
            "source_rect_xyxy": list(GLOBAL_SOURCE),
            "scale": GLOBAL_SCALE,
            "output_size": [1040, 1920],
            "image_pattern": "accuracy/crops/<sample>_aisle.jpg",
            "normalized_to_source": "px=350+x*520, py=0+y*960",
        },
        "detail_view": {
            "kind": "fixed far-channel window, same for every sample",
            "source_frame_size": [1280, 960],
            "source_rect_xyxy": list(DETAIL_SOURCE),
            "scale": DETAIL_SCALE,
            "output_size": [560, 1120],
            "image_pattern": "accuracy/crops/multiscale_v1/detail/<sample>.jpg",
            "normalized_to_source": "px=480+u*280, py=60+v*560",
            "detail_to_global_normalized": (
                "x_global=(130+280*u)/520; y_global=(60+560*v)/960"
            ),
            "generation": "PIL Lanczos resize only; no generative content",
        },
        "images": {},
    }
    for sample in ids:
        frame = Image.open(FRAMES / f"{sample}.jpg").convert("RGB")
        if frame.size != (1280, 960):
            raise SystemExit(f"{sample}: unexpected frame size {frame.size}")
        detail = make_detail(frame)
        detail_path = args.out / "detail" / f"{sample}.jpg"
        detail.save(detail_path, quality=95, subsampling=0)
        global_path = GLOBAL_CROPS / f"{sample}_aisle.jpg"
        manifest["images"][sample] = {
            "global": str(global_path.relative_to(ROOT)).replace("\\", "/"),
            "detail": str(detail_path.relative_to(ROOT)).replace("\\", "/"),
            "global_sha256": sha256(global_path),
            "detail_sha256": sha256(detail_path),
            "global_size": list(Image.open(global_path).size),
            "detail_size": list(detail.size),
        }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    build_layout_check(ids, args.evidence / "geometry_check.jpg")
    build_detail_contact(ids, args.evidence / "detail_contact.jpg")
    print(json.dumps({"samples": len(ids), "manifest": str(args.out / "manifest.json")}, ensure_ascii=False))
    print(f"geometry: {args.evidence / 'geometry_check.jpg'}")
    print(f"detail: {args.evidence / 'detail_contact.jpg'}")


if __name__ == "__main__":
    main()
