"""Extract deterministic frames and experiment montages from the read-only source.

No detector or tracker is used. PIL operations here are geometric preparation
only: fixed crops, resizing and labelled contact sheets.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"D:\File\PROJECT\数据底座\数据底座-货车\视频")
VIDEOS = {
    "north": SOURCE / "A区天花北.mp4",
    "south": SOURCE / "A区天花南.mp4",
}
FPS = 25
OBSERVATIONS = {
    "north": [600, 1200, 1500],
    "south": [600, 900, 1200],
}
LANE_BOX = {"north": (270, 0, 900, 960), "south": (270, 0, 900, 960)}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def extract(video: Path, seconds: float, output: Path) -> dict[str, int | float]:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output),
    ]
    subprocess.run(command, check=True)
    with Image.open(output) as image:
        return {
            "target_seconds": seconds,
            "target_frame_index": round(seconds * FPS),
            "width": image.width,
            "height": image.height,
        }


def wall_clock(seconds: int) -> str:
    # Source README says the shared clip is 2025-10-19 21:59:26 onwards.
    start = datetime(2025, 10, 19, 21, 59, 26)
    return (start + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def lane_crop(source: Path, output: Path, camera: str) -> None:
    with Image.open(source).convert("RGB") as image:
        cropped = image.crop(LANE_BOX[camera])
        cropped = cropped.resize((cropped.width * 2, cropped.height * 2), Image.Resampling.LANCZOS)
        cropped.save(output, quality=94, subsampling=0)


def three_frame_strip(camera: str, base_time: int, frames: Path, output: Path) -> None:
    panel_w, panel_h, label_h = 640, 480, 58
    canvas = Image.new("RGB", (panel_w * 3, panel_h + label_h), "#071018")
    draw = ImageDraw.Draw(canvas)
    for index, delta in enumerate((-10, 0, 10)):
        source = frames / f"{camera}_t{base_time + delta}.jpg"
        with Image.open(source).convert("RGB") as image:
            image.thumbnail((panel_w, panel_h), Image.Resampling.LANCZOS)
            x = index * panel_w + (panel_w - image.width) // 2
            y = label_h + (panel_h - image.height) // 2
            canvas.paste(image, (x, y))
        label = f"{camera.upper()}  {base_time + delta}s  (t{delta:+d}s)"
        draw.text((index * panel_w + 16, 13), label, fill="#63f5d7", font=font(25, True))
        draw.line((index * panel_w, 0, index * panel_w, panel_h + label_h), fill="#445569", width=3)
    canvas.save(output, quality=94, subsampling=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    frames = ROOT / "assets" / "frames"
    crops = ROOT / "assets" / "crops"
    strips = ROOT / "assets" / "strips"
    for folder in (frames, crops, strips):
        folder.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for camera, times in OBSERVATIONS.items():
        for base_time in times:
            for delta in (-10, 0, 10):
                seconds = base_time + delta
                target = frames / f"{camera}_t{seconds}.jpg"
                if args.force or not target.exists():
                    extracted = extract(VIDEOS[camera], seconds, target)
                else:
                    with Image.open(target) as image:
                        extracted = {
                            "target_seconds": seconds,
                            "target_frame_index": round(seconds * FPS),
                            "width": image.width,
                            "height": image.height,
                        }
                manifest.append(
                    {
                        "camera": camera,
                        "video_time_s": seconds,
                        "wall_clock": wall_clock(seconds),
                        "file": str(target.relative_to(ROOT)),
                        **extracted,
                    }
                )
            crop = crops / f"{camera}_t{base_time}_lane.jpg"
            if args.force or not crop.exists():
                lane_crop(frames / f"{camera}_t{base_time}.jpg", crop, camera)
            strip = strips / f"{camera}_{base_time}_strip.jpg"
            if args.force or not strip.exists():
                three_frame_strip(camera, base_time, frames, strip)

    import json

    (ROOT / "data" / "frame_manifest.json").write_text(
        json.dumps(
            {
                "source_video_modified": False,
                "fps": FPS,
                "duration_s": 2659,
                "source": str(SOURCE),
                "frames": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"prepared {len(manifest)} frames, {sum(len(v) for v in OBSERVATIONS.values())} crops/strips")


if __name__ == "__main__":
    main()
