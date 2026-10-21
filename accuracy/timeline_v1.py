"""Build a full-duration, per-camera Doubao timeline with traceable evidence.

The script does not detect or track trucks. FFmpeg selects exact source frames,
Doubao returns the visible-truck candidates, and this script validates and
records that response without filling or smoothing counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from model_probe import ENV_PATH, PROMPT, load_env, probe


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = Path(r"D:\File\PROJECT\数据底座\数据底座-货车\视频")
VIDEOS = {
    "north": VIDEO_DIR / "A区天花北.mp4",
    "south": VIDEO_DIR / "A区天花南.mp4",
}
BUSINESS_START = datetime.fromisoformat("2025-10-19T21:59:26+08:00")
EXPECTED_DURATION = 2659.0
EXPECTED_FRAMES = 66475
FPS = 25
INTERVAL_SECONDS = 60
FRAME_DIR = ROOT / "assets" / "timeline_frames"
RUN_DIR = ROOT / "accuracy" / "runs" / "timeline_v1"
MANIFEST = ROOT / "data" / "timeline_frames_v1.json"
TIMELINE = ROOT / "data" / "timeline_camera_v1.json"


def command(args: list[str]) -> str:
    completed = subprocess.run(
        args, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout


def ffprobe(path: Path) -> dict[str, Any]:
    body = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=width,height,r_frame_rate,nb_frames",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    stream = body["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": int(num) / int(den),
        "nb_frames": int(stream["nb_frames"]),
        "duration_seconds": float(body["format"]["duration"]),
    }


def timecode(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract() -> None:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    for camera, path in VIDEOS.items():
        info = ffprobe(path)
        if (
            info["fps"] != FPS
            or info["nb_frames"] != EXPECTED_FRAMES
            or info["duration_seconds"] != EXPECTED_DURATION
        ):
            raise RuntimeError(f"unexpected source metadata for {camera}: {info}")
        existing = sorted(FRAME_DIR.glob(f"{camera}_*.jpg"))
        if len(existing) == 46:
            print(f"{camera}: reusing {len(existing)} extracted frames")
            continue
        pattern = str(FRAME_DIR / f"{camera}_%03d.jpg")
        command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                (
                    f"select='not(mod(n,{FPS * INTERVAL_SECONDS}))"
                    f"+eq(n,{info['nb_frames'] - 1})',scale=1280:960"
                ),
                "-fps_mode",
                "vfr",
                "-q:v",
                "2",
                pattern,
            ]
        )
        print(f"{camera}: extracted {len(list(FRAME_DIR.glob(f'{camera}_*.jpg')))} frames")


def make_manifest() -> None:
    samples: list[dict[str, Any]] = []
    for camera, path in VIDEOS.items():
        info = ffprobe(path)
        source_hash = sha256(path)
        frame_step = FPS * INTERVAL_SECONDS
        frame_numbers = list(range(0, info["nb_frames"], frame_step))
        frame_numbers.append(info["nb_frames"] - 1)
        for index, frame_number in enumerate(frame_numbers):
            video_seconds = frame_number / info["fps"]
            image = FRAME_DIR / f"{camera}_{index + 1:03d}.jpg"
            if not image.exists():
                raise FileNotFoundError(image)
            business_time = BUSINESS_START + timedelta(seconds=video_seconds)
            samples.append(
                {
                    "sample_id": f"{camera}_{frame_number:06d}",
                    "camera": camera,
                    "source_video": str(path),
                    "source_sha256": source_hash,
                    "frame_number": frame_number,
                    "video_seconds": video_seconds,
                    "video_timecode": timecode(video_seconds),
                    "business_time": business_time.isoformat(timespec="milliseconds"),
                    "business_offset_seconds": 0,
                    "image": image.relative_to(ROOT).as_posix(),
                    "image_sha256": sha256(image),
                }
            )
    payload = {
        "version": "timeline-frames-v1",
        "sampling_method": "FFmpeg select=not(mod(n,1500)), frame 0 plus every 1500 frames",
        "interval_seconds": INTERVAL_SECONDS,
        "business_time_basis": (
            "2025-10-19T21:59:26+08:00 plus zero-based video seconds; "
            "source overlay was checked at 00:00:05 and 00:10:00 for both cameras"
        ),
        "frame_count_per_camera": 46,
        "endpoint_frame": EXPECTED_FRAMES - 1,
        "samples": samples,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {MANIFEST} with {len(samples)} samples")


def read_manifest() -> list[dict[str, Any]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"]


def run_one(sample: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    image = ROOT / sample["image"]
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, retries + 1):
        result = probe("doubao", image, PROMPT, 3000)
        attempts.append(
            {
                "attempt": attempt,
                "timestamp_utc": datetime.now().astimezone().isoformat(timespec="seconds"),
                "ok": bool(result.get("ok")),
                "latency_s": result.get("latency_s"),
                "usage": result.get("usage"),
                "error": result.get("error"),
                "status": result.get("status"),
            }
        )
        if result.get("ok"):
            return {
                **sample,
                "prompt_version": "truck-count-v1",
                "model": result.get("model"),
                "model_id": result.get("model_id"),
                "ok": True,
                "attempts": attempts,
                "latency_s": result.get("latency_s"),
                "usage": result.get("usage"),
                "raw_text": result.get("raw_text"),
                "parsed": result.get("parsed"),
            }
        if attempt < retries:
            time.sleep(2**attempt)
    return {
        **sample,
        "prompt_version": "truck-count-v1",
        "model": "doubao",
        "ok": False,
        "attempts": attempts,
        "latency_s": None,
        "usage": None,
        "raw_text": None,
        "parsed": None,
    }


def run(workers: int) -> None:
    load_env(ENV_PATH)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    samples = read_manifest()
    pending = []
    for sample in samples:
        out = RUN_DIR / f"{sample['sample_id']}.json"
        if out.exists():
            prior = json.loads(out.read_text(encoding="utf-8"))
            if prior.get("ok"):
                continue
        pending.append(sample)
    print(f"{len(samples) - len(pending)} complete, {len(pending)} pending")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, sample): sample for sample in pending}
        for future in as_completed(futures):
            sample = futures[future]
            try:
                payload = future.result()
            except Exception as exc:
                payload = {**sample, "ok": False, "exception": repr(exc), "parsed": None}
            out = RUN_DIR / f"{sample['sample_id']}.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if payload.get("ok"):
                counts = payload["parsed"].get("counts", {})
                print(
                    f"{sample['sample_id']} total={counts.get('total')} "
                    f"vehicles={len(payload['parsed'].get('vehicles', []))} "
                    f"{payload.get('latency_s')}s"
                )
            else:
                print(f"{sample['sample_id']} FAILED")


def validate(parsed: dict[str, Any]) -> dict[str, Any]:
    counts = parsed.get("counts")
    vehicles = parsed.get("vehicles")
    if not isinstance(counts, dict) or not isinstance(vehicles, list):
        return {
            "ok": False,
            "flags": ["schema_invalid"],
            "review_vehicle_count": 0,
        }
    numeric = {}
    for key in ("total", "large", "medium", "small", "unknown"):
        value = counts.get(key)
        numeric[key] = value if isinstance(value, int) and value >= 0 else None
    flags: list[str] = []
    if any(value is None for value in numeric.values()):
        flags.append("count_missing_or_invalid")
    typed = [numeric.get(key) for key in ("large", "medium", "small", "unknown")]
    if all(value is not None for value in typed) and sum(typed) != numeric.get("total"):
        flags.append("type_sum_differs_from_total")
    if numeric.get("total") != len(vehicles):
        flags.append("vehicle_list_differs_from_total")
    uncertain = sum(1 for vehicle in vehicles if vehicle.get("uncertain") is True)
    if uncertain:
        flags.append("uncertain_vehicle")
    if parsed.get("uncertain_reasons"):
        flags.append("model_reported_uncertainty")
    for vehicle in vehicles:
        if vehicle.get("is_truck") is not True:
            flags.append("vehicle_list_contains_non_truck")
            break
        if vehicle.get("size") not in {"large", "medium", "small", "unknown"}:
            flags.append("invalid_vehicle_size")
            break
        box = vehicle.get("bbox")
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(value, (int, float)) for value in box)
            or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)
        ):
            flags.append("invalid_bbox")
    scene_notes = str(parsed.get("scene_notes", "")).lower()
    ambiguity_terms = ("possibly", "might", "overlap", "occlud", "uncertain", "ambiguous")
    if any(term in scene_notes for term in ambiguity_terms):
        flags.append("scene_notes_mention_ambiguity")
    return {
        "ok": not any(
            flag
            in {
                "schema_invalid",
                "count_missing_or_invalid",
                "type_sum_differs_from_total",
                "vehicle_list_differs_from_total",
                "vehicle_list_contains_non_truck",
                "invalid_vehicle_size",
                "invalid_bbox",
            }
            for flag in flags
        ),
        "flags": sorted(set(flags)),
        "review_vehicle_count": uncertain,
    }


def assemble() -> None:
    samples = read_manifest()
    points: list[dict[str, Any]] = []
    failures: list[str] = []
    for sample in samples:
        out = (ROOT / "accuracy" / "runs" / "timeline_v1" / f"{sample['sample_id']}.json")
        if not out.exists():
            failures.append(sample["sample_id"])
            continue
        evidence = json.loads(out.read_text(encoding="utf-8"))
        if not evidence.get("ok"):
            failures.append(sample["sample_id"])
            continue
        parsed = evidence["parsed"]
        checks = validate(parsed)
        counts = parsed.get("counts", {})
        points.append(
            {
                "sample_id": sample["sample_id"],
                "camera": sample["camera"],
                "frame_number": sample["frame_number"],
                "video_seconds": sample["video_seconds"],
                "video_timecode": sample["video_timecode"],
                "business_time": sample["business_time"],
                "counts": {
                    "total": counts.get("total"),
                    "large": counts.get("large"),
                    "medium": counts.get("medium"),
                    "small": counts.get("small"),
                    "unknown": counts.get("unknown"),
                },
                "listed_vehicle_count": len(parsed.get("vehicles", [])),
                "review_count": len(checks["flags"]),
                "review_vehicle_count": checks["review_vehicle_count"],
                "review_flags": checks["flags"],
                "review_required": bool(checks["flags"]),
                "schema_valid": checks["ok"],
                "nearest_sample_video_seconds": sample["video_seconds"],
                "nearest_sample_business_time": sample["business_time"],
                "image": sample["image"],
                "evidence": out.relative_to(ROOT).as_posix(),
                "latency_s": evidence.get("latency_s"),
                "usage": evidence.get("usage"),
                "vehicles": parsed.get("vehicles", []),
                "scene_notes": parsed.get("scene_notes"),
                "uncertain_reasons": parsed.get("uncertain_reasons", []),
            }
        )
    points.sort(key=lambda point: (point["camera"], point["video_seconds"]))
    total_usage = {}
    for point in points:
        usage = point.get("usage") or {}
        for key, value in usage.items():
            if isinstance(value, int):
                total_usage[key] = total_usage.get(key, 0) + value
    payload = {
        "version": "timeline-camera-v1",
        "status": "model-estimate-pending-human-review",
        "scope": "per-camera visible truck count; NOT a cross-camera unique-vehicle count",
        "count_definition": (
            "Every distinct truck body visible in the camera image; a tractor and its trailer "
            "count once; forklifts, cars, vans and people are excluded."
        ),
        "source": {
            "videos": {camera: str(path) for camera, path in VIDEOS.items()},
            "duration_seconds": EXPECTED_DURATION,
            "frames": EXPECTED_FRAMES,
            "fps": FPS,
            "resolution": "1280x960",
        },
        "business_time": {
            "start": BUSINESS_START.isoformat(timespec="seconds"),
            "offset_seconds": {"north": 0, "south": 0},
            "status": (
                "nominal zero-based time; source overlays matched at the start and middle, "
                "then showed a roughly +/-1 second residual at the end"
            ),
            "uncertainty_seconds": 2,
            "source_overlay_checks": [
                {
                    "camera": "north",
                    "video_seconds": 0,
                    "frame_number": 0,
                    "overlay": "2025-10-19 21:59:26",
                },
                {
                    "camera": "south",
                    "video_seconds": 0,
                    "frame_number": 0,
                    "overlay": "2025-10-19 21:59:26",
                },
                {
                    "camera": "north",
                    "video_seconds": 600,
                    "frame_number": 15000,
                    "overlay": "2025-10-19 22:09:26",
                },
                {
                    "camera": "south",
                    "video_seconds": 600,
                    "frame_number": 15000,
                    "overlay": "2025-10-19 22:09:26",
                },
                {
                    "camera": "north",
                    "video_seconds": 2640,
                    "frame_number": 66000,
                    "overlay": "2025-10-19 22:43:27",
                },
                {
                    "camera": "south",
                    "video_seconds": 2640,
                    "frame_number": 66000,
                    "overlay": "2025-10-19 22:43:25",
                },
            ],
        },
        "sampling": {
            "interval_seconds": INTERVAL_SECONDS,
            "frame_step": FPS * INTERVAL_SECONDS,
            "points_per_camera": 46,
            "endpoint_frame": EXPECTED_FRAMES - 1,
            "interpolation": "none; query nearest_sample_* rather than inventing a count between samples",
        },
        "model": {
            "name": "doubao",
            "id": json.loads((RUN_DIR / "north_000000.json").read_text(encoding="utf-8")).get("model_id"),
            "prompt_version": "truck-count-v1",
            "temperature": 0,
        },
        "coverage": {
            "requested_samples": len(samples),
            "completed_points": len(points),
            "failed_sample_ids": failures,
        },
        "usage_totals": total_usage,
        "review_policy": {
            "review_required_when": [
                "any vehicle is marked uncertain",
                "the model reports uncertainty reasons",
                "count total disagrees with the vehicle list or type sum",
                "the vehicle list contains a non-truck or invalid type",
                "scene notes explicitly mention ambiguity terms",
            ],
            "review_vehicle_count": "number of vehicles with uncertain=true, not total review issues",
        },
        "points": points,
    }
    TIMELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"wrote {TIMELINE}: {len(points)} points, "
        f"{len(failures)} failures, usage={total_usage}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["all", "extract", "manifest", "run", "assemble"])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.action in {"all", "extract"}:
        extract()
    if args.action in {"all", "manifest"}:
        make_manifest()
    if args.action in {"all", "run"}:
        run(args.workers)
    if args.action in {"all", "assemble"}:
        assemble()


if __name__ == "__main__":
    main()
