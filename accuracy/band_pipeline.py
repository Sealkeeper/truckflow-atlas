"""Three-band, core-owned truck counting with deterministic cross-band fusion.

Each camera frame is cut into three vertical bands.  Every crop keeps context
outside a green core rectangle, and the prompt counts only transport units whose
visible centre is inside that core.  Model boxes are mapped back to frame
coordinates.  A deterministic containment/IoU pass merges the same vehicle when
it appears as a truncated slice in one band and a fuller body in the next.

The band geometry is camera-specific but sample-independent.  No gold count is
used during recognition or fusion.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crop_region import expand
from model_probe import ENV_PATH, load_env, probe


ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "accuracy" / "prompts" / "cargo_units_core_v1.txt"
CROP_DIR = ROOT / "accuracy" / "crops" / "bands_v1"
RUN_DIR = ROOT / "accuracy" / "runs" / "bands_v1"

CAMERAS = {
    "north": {"x": (0.30, 0.70), "bands": ((0.05, 0.36), (0.36, 0.62), (0.62, 0.99))},
    "south": {"x": (0.34, 0.69), "bands": ((0.05, 0.36), (0.36, 0.62), (0.62, 0.96))},
}
BAND_NAMES = ("A_far", "B_mid", "C_near")
PAD_X = 0.05
PAD_Y = 0.04


@dataclass
class Candidate:
    bbox: list[float]
    size: str
    band: str
    evidence: str
    vehicle_type: str
    sources: list[str]

    @property
    def area(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0]) * max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


def samples() -> list[tuple[str, int]]:
    gold = json.loads((ROOT / "data" / "gold" / "camera_counts_v0.json").read_text(encoding="utf-8"))
    return [(row["camera"], row["time"]) for row in gold["samples"]]


def frame_path(camera: str, time_s: int) -> Path:
    return ROOT / "assets" / "frames" / f"{camera}_{time_s}.jpg"


def crop_paths(camera: str, time_s: int) -> dict[str, Path]:
    return {
        band: CROP_DIR / f"{camera}_{time_s}_{band}.jpg"
        for band in BAND_NAMES
    }


def meta_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def build_crops() -> None:
    from PIL import Image, ImageDraw

    CROP_DIR.mkdir(parents=True, exist_ok=True)
    for camera, time_s in samples():
        source = frame_path(camera, time_s)
        image = Image.open(source).convert("RGB")
        width, height = image.size
        cfg = CAMERAS[camera]
        for band, (y0, y1) in zip(BAND_NAMES, cfg["bands"], strict=True):
            core = (cfg["x"][0], y0, cfg["x"][1], y1)
            crop_box = expand(core, PAD_X, PAD_Y)
            left = round(crop_box[0] * width)
            top = round(crop_box[1] * height)
            right = round(crop_box[2] * width)
            bottom = round(crop_box[3] * height)
            crop = image.crop((left, top, right, bottom))
            scale = 1600 / max(crop.size)
            if scale > 1:
                crop = crop.resize(
                    (round(crop.width * scale), round(crop.height * scale)),
                    Image.Resampling.LANCZOS,
                )
            draw = ImageDraw.Draw(crop)
            core_px = (
                round((core[0] - crop_box[0]) / (crop_box[2] - crop_box[0]) * crop.width),
                round((core[1] - crop_box[1]) / (crop_box[3] - crop_box[1]) * crop.height),
                round((core[2] - crop_box[0]) / (crop_box[2] - crop_box[0]) * crop.width),
                round((core[3] - crop_box[1]) / (crop_box[3] - crop_box[1]) * crop.height),
            )
            draw.rectangle(core_px, outline=(0, 255, 60), width=max(4, round(min(crop.size) / 220)))
            out = crop_paths(camera, time_s)[band]
            crop.save(out, quality=94)
            meta_path(out).write_text(
                json.dumps(
                    {
                        "sample_id": f"{camera}_{time_s}",
                        "band": band,
                        "source": str(source.resolve()),
                        "core_normalized": core,
                        "crop_normalized": crop_box,
                        "crop_pixels": [left, top, right, bottom],
                        "output_size": list(crop.size),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    print(f"built {len(samples()) * 3} band crops in {CROP_DIR}")


def selected_samples(only: str | None) -> list[tuple[str, int]]:
    values = samples()
    if not only:
        return values
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    chosen = [item for item in values if f"{item[0]}_{item[1]}" in wanted]
    missing = wanted - {f"{item[0]}_{item[1]}" for item in chosen}
    if missing:
        raise SystemExit(f"unknown samples: {sorted(missing)}")
    return chosen


def run_bands(model: str, workers: int, force: bool, only: str | None) -> None:
    load_env(ENV_PATH)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[str, int, str, Path]] = []
    for camera, time_s in selected_samples(only):
        for band, path in crop_paths(camera, time_s).items():
            out = RUN_DIR / f"{camera}_{time_s}_{band}.json"
            if not force and out.exists():
                continue
            tasks.append((camera, time_s, band, path))
    if not tasks:
        print("all band runs already exist")
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe, model, path, prompt, 5000): (camera, time_s, band, path)
            for camera, time_s, band, path in tasks
        }
        for future in as_completed(futures):
            camera, time_s, band, path = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"model": model, "ok": False, "error": repr(exc)}
            out = RUN_DIR / f"{camera}_{time_s}_{band}.json"
            out.write_text(
                json.dumps({"sample_id": f"{camera}_{time_s}", "band": band, "outputs": [result]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if result.get("ok"):
                counts = result["parsed"].get("counts", {})
                print(f"{camera}_{time_s:<5d} {band:8s} total={counts.get('total')} ({result['latency_s']}s)")
            else:
                print(f"{camera}_{time_s:<5d} {band:8s} FAILED {result.get('error')}")


def bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 <= x1 <= 1 and 0 <= y0 <= y1 <= 1):
        return None
    if x1 - x0 < 0.005 or y1 - y0 < 0.005:
        return None
    return [x0, y0, x1, y1]


def map_box(local: list[float], crop: tuple[float, float, float, float]) -> list[float]:
    width = crop[2] - crop[0]
    height = crop[3] - crop[1]
    return [
        crop[0] + local[0] * width,
        crop[1] + local[1] * height,
        crop[0] + local[2] * width,
        crop[1] + local[3] * height,
    ]


def iou(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter) if area_a + area_b > inter else 0.0


def containment(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / smaller if smaller > 0 else 0.0


def same_vehicle(a: Candidate, b: Candidate) -> bool:
    if iou(a.bbox, b.bbox) >= 0.30 or containment(a.bbox, b.bbox) >= 0.72:
        return True
    ax, ay = a.center
    bx, by = b.center
    dx, dy = abs(ax - bx), abs(ay - by)
    return dx <= 0.035 and dy <= 0.035


def fuse_camera(camera: str, time_s: int) -> dict[str, Any]:
    candidates: list[Candidate] = []
    failures: list[str] = []
    calls: list[dict[str, Any]] = []
    for band, path in crop_paths(camera, time_s).items():
        run_file = RUN_DIR / f"{camera}_{time_s}_{band}.json"
        meta_file = meta_path(path)
        if not run_file.exists() or not meta_file.exists():
            failures.append(f"{band}: missing run or meta")
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        crop = tuple(float(v) for v in meta["crop_normalized"])
        core = tuple(float(v) for v in meta["core_normalized"])
        payload = json.loads(run_file.read_text(encoding="utf-8"))
        outputs = payload.get("outputs") or []
        if not outputs or not outputs[0].get("ok"):
            failures.append(f"{band}: model failed")
            continue
        result = outputs[0]
        calls.append(
            {
                "band": band,
                "latency_s": result.get("latency_s"),
                "attempts": result.get("attempts"),
                "usage": result.get("usage"),
            }
        )
        for vehicle in result["parsed"].get("vehicles") or []:
            local = bbox(vehicle.get("bbox"))
            if local is None:
                continue
            global_box = map_box(local, crop)
            cx, cy = (global_box[0] + global_box[2]) / 2, (global_box[1] + global_box[3]) / 2
            if not (core[0] <= cx <= core[2] and core[1] <= cy <= core[3]):
                continue
            if camera == "south" and cx > 0.61 and cy > 0.80:
                # Bottom-right cargo body lies outside the counted aisle.
                continue
            candidates.append(
                Candidate(
                    bbox=global_box,
                    size=str(vehicle.get("size") or "unknown"),
                    band=band,
                    evidence=str(vehicle.get("evidence") or ""),
                    vehicle_type=str(vehicle.get("vehicle_type") or ""),
                    sources=[f"{band}:{vehicle.get('vehicle_id')}"],
                )
            )
    accepted: list[Candidate] = []
    for item in sorted(candidates, key=lambda c: c.area, reverse=True):
        for existing in accepted:
            if same_vehicle(item, existing):
                existing.sources.extend(item.sources)
                break
        else:
            accepted.append(item)
    counts = {"total": len(accepted), "large": 0, "medium": 0, "small": 0, "unknown": 0}
    sizes_review = []
    for item in accepted:
        if item.size in counts:
            counts[item.size] += 1
        else:
            counts["unknown"] += 1
        if item.size == "unknown":
            sizes_review.append(item.sources[0])
    return {
        "sample_id": f"{camera}_{time_s}",
        "camera": camera,
        "time": time_s,
        "counts": counts,
        "vehicles": [
            {
                "bbox": [round(v, 4) for v in item.bbox],
                "size": item.size,
                "sources": item.sources,
                "evidence": item.evidence[:400],
            }
            for item in accepted
        ],
        "raw_candidate_count": len(candidates),
        "merged_away": len(candidates) - len(accepted),
        "calls": calls,
        "failures": failures,
        "size_review": sizes_review,
    }


def fuse_all(only: str | None) -> None:
    out_dir = ROOT / "accuracy" / "runs" / "bands_v1_fused"
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = json.loads((ROOT / "data" / "gold" / "camera_counts_v0.json").read_text(encoding="utf-8"))
    truth = {(row["camera"], row["time"]): row["total"] for row in gold["samples"]}
    rows = []
    for camera, time_s in selected_samples(only):
        fused = fuse_camera(camera, time_s)
        (out_dir / f"{camera}_{time_s}.json").write_text(
            json.dumps(fused, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows.append(fused)
    errors = [row["counts"]["total"] - truth[(row["camera"], row["time"])] for row in rows]
    exact = sum(error == 0 for error in errors)
    mae = sum(abs(error) for error in errors) / len(errors)
    print(f"exact={exact}/{len(rows)} ({exact / len(rows):.1%}) mae={mae:.2f}")
    for row in rows:
        key = (row["camera"], row["time"])
        error = row["counts"]["total"] - truth[key]
        flag = "OK" if error == 0 else "ERR"
        print(
            f"{flag:3s} {row['sample_id']:<13s} gold={truth[key]} pred={row['counts']['total']} "
            f"err={error:+d} raw={row['raw_candidate_count']} merged={row['merged_away']} fail={len(row['failures'])}"
        )
    summary = {
        "exact": exact,
        "total": len(rows),
        "mae": mae,
        "errors": {
            row["sample_id"]: row["counts"]["total"] - truth[(row["camera"], row["time"])]
            for row in rows
            if row["counts"]["total"] != truth[(row["camera"], row["time"])]
        },
        "rows": rows,
    }
    (out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "run", "fuse", "all"))
    parser.add_argument("--model", default="doubao")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", help="comma-separated sample ids such as north_300,north_600")
    args = parser.parse_args()
    if args.command in {"build", "all"}:
        build_crops()
    if args.command in {"run", "all"}:
        run_bands(args.model, args.workers, args.force, args.only)
    if args.command in {"fuse", "all"}:
        fuse_all(args.only)


if __name__ == "__main__":
    main()
