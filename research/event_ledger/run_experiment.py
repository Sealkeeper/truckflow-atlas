"""One multi-image VLM call per preregistered window, followed by local replay."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = Path(r"D:\File\PROJECT\codex\codex-货车\all-sessions-can-see")
VIDEOS = Path(r"D:\File\PROJECT\数据底座\数据底座-货车\视频")
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(PUBLIC / "accuracy"))
from ledger import EventLedger
from model_probe import extract_json, load_env

# Frozen before any new response; labels are never included in API content.
WINDOWS = [
    {"name": "north_far_540_600", "camera": "north", "times": [540, 570, 600], "mechanism": "distant bodies missed/merged", "user_target": 600},
    {"name": "north_entry_2100_2160", "camera": "north", "times": [2100, 2130, 2160], "mechanism": "visible entry candidate", "user_target": 2100},
    {"name": "south_boundary_2580_2600", "camera": "south", "times": [2580, 2590, 2600], "mechanism": "partial cargo at image boundary", "user_target": 2600},
]
PROMPT = """你是固定天花摄像头的货车视觉事件记录员。下面是同一机位按时间排序的三张原图。一次完成全部观察并输出严格JSON。
计数口径：每张图实际可见、可辨的独立货车车体；独立货厢可单计，牵引车与其挂车只计一辆。叉车、人物、轿车不计。车顶或货厢仅局部可见但可确认货车仍计。完全遮挡或已出画的车辆不计当前可见数量。
给每辆车在本窗口内一个稳定id。对每张图分别列出当前可见车辆，必须给该图归一化bbox和当前可见证据。远端并排或前后紧邻的货厢可能属于独立车，请逐个观察；不能仅继承上一张数量。
附带第一张图的旧模型候选仅作可被推翻的初始化；它可能漏车、把两辆合并或重复。你必须直接依据三图纠正初始集合，不能把旧数量当真值。初次纠正使用seed_corrected，不要伪造物理进入事件。
每帧变化事件仅允许entered/exited/still_visible/occluded/reappeared/seed_corrected。entered必须有穿越画面/通道边界证据；从看漏到看见不等于进入；相似颜色不等于同一车。身份或事件无法判断时写uncertainties，禁止用平滑数量消除变化。
JSON结构：{"snapshots":[{"time_s":0,"declared_total":0,"visible_vehicles":[{"id":"v1","bbox":[0,0,1,1],"appearance":"车顶、货厢、车头特征","current_evidence":"本图可见证据"}],"events":[{"id":"v1","type":"still_visible","evidence":"该时刻的事件依据"}],"uncertainties":[]}],"window_notes":"限制与遮挡"}。
timestamps必须逐一对应图像标签，snapshots数量必须与图像数量完全一致。不要markdown。
"""


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    points = json.loads((PUBLIC / "data/timeline_camera_v1.json").read_text(encoding="utf-8"))["points"]
    manifest = {"experiment": "event-ledger-v1", "selection": "three mechanism windows frozen before new inference", "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(), "windows": []}
    for w in WINDOWS:
        seed = next(p for p in points if p["camera"] == w["camera"] and p["video_seconds"] == w["times"][0])
        record = {**w, "seed_source": seed["evidence"], "seed_count": seed["counts"]["total"], "images": []}
        for t in w["times"]:
            frame = HERE / "frames" / f"{w['camera']}_{t}.jpg"
            if not frame.exists():
                frame.parent.mkdir(parents=True, exist_ok=True)
                video = VIDEOS / ("A区天花北.mp4" if w["camera"] == "north" else "A区天花南.mp4")
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame)], check=True)
            record["images"].append({"time_s": t, "frame_number": t * 25, "path": str(frame.relative_to(HERE)), "sha256": sha(frame)})
        record["seed"] = {"time_s": seed["video_seconds"], "vehicles": [{"id": f"seed_{i+1}", "bbox": v["bbox"], "identity_clues": v.get("identity_clues", "")} for i, v in enumerate(seed["vehicles"])]}
        manifest["windows"].append(record)
    write_json(HERE / "manifest.json", manifest)
    (HERE / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    return manifest


def call_window(w):
    path = HERE / "raw" / f"{w['name']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    content = [{"type": "text", "text": PROMPT + "\n初始化候选（不是标签）：" + json.dumps(w["seed"], ensure_ascii=False)}]
    for item in w["images"]:
        image = HERE / item["path"]
        content.extend([{"type": "text", "text": f"机位{w['camera']}, time_s={item['time_s']}"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode()}}])
    payload = {"model": os.environ.get("DOUBAO_MODEL", "ep-20260828174616-dthpx"), "temperature": 0, "max_tokens": 5000, "messages": [{"role": "user", "content": content}]}
    start = time.perf_counter()
    record = {"window": w["name"], "model": payload["model"], "image_count": len(w["images"]), "attempts": 1, "ok": False}
    try:
        response = requests.post(os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + os.environ["DOUBAO_API_KEY"]}, json=payload, timeout=180)
        record["status"] = response.status_code
        response.raise_for_status()
        body = response.json()
        raw = body["choices"][0]["message"]["content"]
        record.update(raw_text=raw, usage=body.get("usage"), finish_reason=body["choices"][0].get("finish_reason"))
        parsed = extract_json(raw)
        if [x["time_s"] for x in parsed["snapshots"]] != w["times"]:
            raise ValueError("response timestamps do not match input images")
        record.update(ok=True, parsed=parsed)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["latency_s"] = round(time.perf_counter() - start, 3)
    write_json(path, record)
    return record


def replay(manifest, records):
    review = json.loads((PUBLIC / "accuracy/reviewed/user-final-review-v2-2026-10-21.json").read_text(encoding="utf-8"))
    truth = {(cam, s["time"]): count for s in review["samples"] for cam, count in s["camera_counts"].items()}
    rows, windows = [], []
    for w, record in zip(manifest["windows"], records):
        if not record["ok"]:
            windows.append({"name": w["name"], "ok": False, "error": record.get("error")})
            continue
        ledger = EventLedger(w["camera"])
        history = [ledger.apply(snapshot) for snapshot in record["parsed"]["snapshots"]]
        windows.append({"name": w["name"], "ok": True, "snapshots": history,
                        "aggregation_wait_s": w["times"][-1] - w["times"][0],
                        "latency_s": record["latency_s"], "usage": record.get("usage"),
                        "offline_window_completion_delay_s": w["times"][-1] - w["times"][0] + record["latency_s"]})
        for out in history:
            key = (w["camera"], out["time_s"])
            if key in truth:
                baseline_path = PUBLIC / "accuracy/runs/aisle_doubao" / f"{key[0]}_{int(key[1])}_aisle.json"
                baseline_record = json.loads(baseline_path.read_text(encoding="utf-8"))["runs"][0]
                baseline_count = baseline_record["parsed"]["counts"]["total"] if baseline_record["ok"] else None
                rows.append({**out, "truth": truth[key], "error": out["predicted_count"] - truth[key],
                             "pure_aisle_baseline": baseline_count,
                             "baseline_source": str(baseline_path.relative_to(PUBLIC)),
                             "uses_future_frames": out["time_s"] < w["times"][-1],
                             "output_delay_from_target_s": w["times"][-1] - out["time_s"] + record["latency_s"]})
    latency = sorted(r["latency_s"] for r in records)
    metrics = {"experiment": "event-ledger-v1", "new_calls": len(records), "new_images": sum(r["image_count"] for r in records), "successful_windows": sum(r["ok"] for r in records), "failed_windows": sum(not r["ok"] for r in records), "user_reviewed_points": len(rows), "exact": sum(x["error"] == 0 for x in rows), "mae": sum(abs(x["error"]) for x in rows) / len(rows) if rows else None, "under": sum(max(0, -x["error"]) for x in rows), "over": sum(max(0, x["error"]) for x in rows), "review_required_points": sum(x["review_required"] for x in rows), "mean_latency_s": sum(latency) / len(latency), "p95_latency_s": latency[max(0, math.ceil(.95 * len(latency)) - 1)], "serial_latency_s": sum(latency), "total_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in records), "bootstrap_calls_reused": len(records), "live_bootstrap_cost_included": False, "calls_per_input_frame_new": len(records) / sum(r["image_count"] for r in records), "event_truth_status": "not_user_labeled", "id_truth_status": "not_user_labeled", "unique_count_status": "not_evaluated_single_camera_windows", "rows": rows, "windows": windows}
    accepted = [x for x in rows if not x["review_required"]]
    baseline_errors = [x["pure_aisle_baseline"] - x["truth"] for x in rows if x["pure_aisle_baseline"] is not None]
    metrics.update({
        "fixed_planned_N": len(WINDOWS), "valid_N": len(rows),
        "evaluation_split": "reused_development_samples_not_independent_validation",
        "truth_source": "accuracy/reviewed/user-final-review-v2-2026-10-21.json",
        "automatic_acceptance": {"accepted_N": len(accepted), "accepted_correct": sum(x["error"] == 0 for x in accepted),
                                 "accepted_wrong": sum(x["error"] != 0 for x in accepted),
                                 "coverage": len(accepted) / len(WINDOWS),
                                 "accepted_accuracy": sum(x["error"] == 0 for x in accepted) / len(accepted) if accepted else None},
        "same_point_pure_aisle_baseline": {"valid_N": len(baseline_errors), "exact": sum(x == 0 for x in baseline_errors),
                                            "mae": sum(abs(x) for x in baseline_errors) / len(baseline_errors) if baseline_errors else None,
                                            "under_units": sum(max(0, -x) for x in baseline_errors), "over_units": sum(max(0, x) for x in baseline_errors)},
        "cost_caveat": "Seed candidates reuse 3 earlier model outputs; their calls/tokens/latency are excluded. Fewer HTTP requests does not establish lower image/token cost.",
        "latency_caveat": "N=3 empirical p95 equals maximum. Aggregation wait and bootstrap inference must be added for live operation. north_2100 is retrospective because future frames are included.",
    })
    write_json(HERE / "metrics.json", metrics)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Replay cached responses only; fail if any cache is absent.")
    args = parser.parse_args()
    manifest = prepare()
    if args.prepare_only:
        print("prepared", len(manifest["windows"]), "windows; no model calls")
        return
    if args.offline:
        records = [json.loads((HERE / "raw" / f"{w['name']}.json").read_text(encoding="utf-8")) for w in manifest["windows"]]
    else:
        load_env(PUBLIC / ".env")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            records = list(pool.map(call_window, manifest["windows"]))
    metrics = replay(manifest, records)
    print(json.dumps({k: v for k, v in metrics.items() if k not in {"rows", "windows"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
