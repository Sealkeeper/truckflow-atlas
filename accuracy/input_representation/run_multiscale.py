"""Run the frozen single-call global+detail experiment.

There is one primary request per sample. Transport failures may be retried only
under the pre-registered policy. A successful HTTP response with an invalid
answer is recorded as a failed sample and is never repaired or resampled.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import math
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = Path(
    r"D:\File\PROJECT\codex\codex-货车\codexcodex-货车\.env"
)
DEFAULT_MANIFEST = ROOT / "accuracy" / "crops" / "multiscale_v1" / "manifest.json"
DEFAULT_PROMPT = ROOT / "accuracy" / "prompts" / "multiscale_v1.txt"
DEFAULT_PREREG = ROOT / "accuracy" / "input_representation" / "preregistration.json"
DEFAULT_OUT = ROOT / "accuracy" / "runs" / "multiscale_v1"

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_env(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"environment file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def data_uri(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    mime = "image/png" if suffix == "png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def check_contract(
    manifest: dict[str, Any],
    prereg: dict[str, Any],
    prompt_path: Path,
    prompt: str,
) -> None:
    if prereg.get("status") != "frozen-before-primary-call":
        raise SystemExit("pre-registration is not frozen before the primary call")
    if prereg.get("sample_count") != 20 or manifest.get("sample_count") != 20:
        raise SystemExit("pre-registration and manifest must both contain 20 samples")
    if prereg.get("samples") != manifest.get("samples"):
        raise SystemExit("pre-registered sample order differs from manifest")
    if prereg.get("prompt", {}).get("sha256") != sha256_file(prompt_path):
        raise SystemExit("prompt hash differs from pre-registration")
    if prereg.get("prompt", {}).get("text_sha256") != sha256_bytes(prompt.encode("utf-8")):
        raise SystemExit("prompt text hash differs from pre-registration")
    if prereg.get("manifest_sha256") != sha256_file(DEFAULT_MANIFEST):
        raise SystemExit("manifest hash differs from pre-registration")
    for key in ("model_id", "temperature", "max_tokens", "input_order"):
        if key not in prereg.get("request", {}):
            raise SystemExit(f"missing pre-registered request field: {key}")


def validate_parsed(parsed: Any) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    if not isinstance(parsed, dict):
        return ["top-level JSON must be an object"], None
    if parsed.get("coordinate_system") != "original_frame_1280x960_normalized_xyxy":
        errors.append("coordinate_system is not the frozen original-frame system")

    counts = parsed.get("counts")
    vehicles = parsed.get("vehicles")
    if not isinstance(counts, dict):
        errors.append("counts must be an object")
        counts = {}
    if not isinstance(vehicles, list):
        errors.append("vehicles must be an array")
        vehicles = []

    numeric_counts: dict[str, int] = {}
    for key in ("total", "large", "medium", "small", "unknown"):
        value = counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"counts.{key} must be a non-negative integer")
        else:
            numeric_counts[key] = value
    total = numeric_counts.get("total")
    if total is not None and total != len(vehicles):
        errors.append("counts.total does not equal len(vehicles)")
    if len(numeric_counts) == 5:
        size_sum = sum(numeric_counts[key] for key in ("large", "medium", "small", "unknown"))
        if size_sum != numeric_counts["total"]:
            errors.append("size counts do not sum to counts.total")

    ids: list[str] = []
    size_counts = {"large": 0, "medium": 0, "small": 0, "unknown": 0}
    seen_counts = {"global": 0, "detail": 0, "both": 0}
    boxes: list[list[float]] = []
    all_sizes = set(size_counts)
    all_visible = {"full", "partial_top", "partial_side", "partial_rear", "trailer_only"}

    for index, vehicle in enumerate(vehicles):
        prefix = f"vehicles[{index}]"
        if not isinstance(vehicle, dict):
            errors.append(f"{prefix} must be an object")
            continue
        identifier = vehicle.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        else:
            ids.append(identifier)

        bbox = vehicle.get("bbox_full")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox)
            or any(not math.isfinite(float(value)) for value in bbox)
        ):
            errors.append(f"{prefix}.bbox_full must contain four finite numbers")
        else:
            box = [float(value) for value in bbox]
            boxes.append(box)
            x0, y0, x1, y1 = box
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                errors.append(f"{prefix}.bbox_full is outside [0,1] or not x0<x1,y0<y1")

        size = vehicle.get("size")
        if size not in all_sizes:
            errors.append(f"{prefix}.size is invalid")
        else:
            size_counts[size] += 1
        if vehicle.get("visible") not in all_visible:
            errors.append(f"{prefix}.visible is invalid")
        if vehicle.get("is_truck") is not True:
            errors.append(f"{prefix}.is_truck must be true")
        if not isinstance(vehicle.get("uncertain"), bool):
            errors.append(f"{prefix}.uncertain must be boolean")
        if not isinstance(vehicle.get("uncertain_reasons"), list):
            errors.append(f"{prefix}.uncertain_reasons must be an array")
        if not isinstance(vehicle.get("identity_clues"), str) or not vehicle["identity_clues"].strip():
            errors.append(f"{prefix}.identity_clues must be a non-empty string")
        if not isinstance(vehicle.get("evidence"), str) or not vehicle["evidence"].strip():
            errors.append(f"{prefix}.evidence must be a non-empty string")

        seen = vehicle.get("seen_in")
        if not isinstance(seen, list) or not seen or any(value not in {"global", "detail"} for value in seen):
            errors.append(f"{prefix}.seen_in must be a non-empty global/detail array")
        elif len(set(seen)) != len(seen):
            errors.append(f"{prefix}.seen_in contains duplicates")
        else:
            seen_counts["global"] += "global" in seen
            seen_counts["detail"] += "detail" in seen
            seen_counts["both"] += len(set(seen)) == 2

    if len(set(ids)) != len(ids):
        errors.append("vehicle ids are not unique")
    if numeric_counts and size_counts != {
        key: numeric_counts.get(key) for key in ("large", "medium", "small", "unknown")
    }:
        errors.append("declared size counts do not match vehicle sizes")
    if not isinstance(parsed.get("scene_notes"), str):
        errors.append("scene_notes must be a string")
    if not isinstance(parsed.get("uncertain_reasons"), list):
        errors.append("uncertain_reasons must be an array")

    audit = {
        "vehicle_count": len(vehicles),
        "unique_id_count": len(set(ids)),
        "declared_counts": counts,
        "observed_size_counts": size_counts,
        "seen_in_counts": seen_counts,
        "bbox_count": len(boxes),
        "bbox_duplicate_candidates_iou_ge_0_85": pairwise_high_iou(boxes),
    }
    return errors, audit


def pairwise_high_iou(boxes: list[list[float]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for left in range(len(boxes)):
        for right in range(left + 1, len(boxes)):
            intersection = max(
                0.0,
                min(boxes[left][2], boxes[right][2]) - max(boxes[left][0], boxes[right][0]),
            ) * max(
                0.0,
                min(boxes[left][3], boxes[right][3]) - max(boxes[left][1], boxes[right][1]),
            )
            area_left = (boxes[left][2] - boxes[left][0]) * (boxes[left][3] - boxes[left][1])
            area_right = (boxes[right][2] - boxes[right][0]) * (boxes[right][3] - boxes[right][1])
            union = area_left + area_right - intersection
            iou = intersection / union if union > 0 else 0.0
            if iou >= 0.85:
                result.append({"left_index": left, "right_index": right, "iou": round(iou, 4)})
    return result


def boxes_to_full_pixels(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for vehicle in parsed.get("vehicles", []):
        bbox = vehicle.get("bbox_full")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = bbox
        result.append(
            {
                "id": vehicle.get("id"),
                "bbox_full_normalized": bbox,
                "bbox_full_pixels_1280x960": [
                    round(float(x0) * 1280, 2),
                    round(float(y0) * 960, 2),
                    round(float(x1) * 1280, 2),
                    round(float(y1) * 960, 2),
                ],
            }
        )
    return result


def request_once(
    session: requests.Session,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    attempt_number: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    started_at = utc_now()
    started = time.perf_counter()
    try:
        response = session.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(20, 240),
        )
        latency = round(time.perf_counter() - started, 3)
        error_text = None if response.ok else response.text[:4000]
        record = {
            "attempt": attempt_number,
            "started_at": started_at,
            "latency_s": latency,
            "http_status": response.status_code,
            "url": response.url,
            "response_headers_subset": {
                key: response.headers.get(key)
                for key in ("x-request-id", "x-tt-logid", "content-type")
                if response.headers.get(key)
            },
            "response_text_if_error": error_text,
        }
        retryable_status = response.status_code in RETRY_STATUS
        if not response.ok:
            record["transport_error"] = f"HTTP {response.status_code}"
            return record, None, retryable_status
        try:
            body = response.json()
        except ValueError as exc:
            record["transport_error"] = f"ResponseJSONError: {exc}"
            record["raw_response_text"] = response.text[:20000]
            return record, None, False
        record["raw_response_body"] = body
        return record, body, False
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        record = {
            "attempt": attempt_number,
            "started_at": started_at,
            "latency_s": round(time.perf_counter() - started, 3),
            "http_status": None,
            "transport_error": f"{type(exc).__name__}: {exc}",
        }
        return record, None, True
    except requests.exceptions.RequestException as exc:
        record = {
            "attempt": attempt_number,
            "started_at": started_at,
            "latency_s": round(time.perf_counter() - started, 3),
            "http_status": getattr(getattr(exc, "response", None), "status_code", None),
            "transport_error": f"{type(exc).__name__}: {exc}",
        }
        return record, None, False


def extract_content_and_finish(body: dict[str, Any]) -> tuple[str, str | None, str | None]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", None, "response has no choices"
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        return "", choice.get("finish_reason") if isinstance(choice, dict) else None, "response has no message"
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str):
        return "", choice.get("finish_reason"), "message content is not text"
    return content, choice.get("finish_reason"), None


def parse_json(text: str) -> tuple[Any, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        return None, "markdown code fence is forbidden by the frozen prompt"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}"


def run(args: argparse.Namespace) -> None:
    load_env(args.env)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    prompt = args.prompt.read_text(encoding="utf-8")
    check_contract(manifest, prereg, args.prompt, prompt)

    model_id = prereg["request"]["model_id"]
    temperature = prereg["request"]["temperature"]
    max_tokens = prereg["request"]["max_tokens"]
    if os.environ.get("DOUBAO_MODEL") and os.environ["DOUBAO_MODEL"] != model_id:
        raise SystemExit("DOUBAO_MODEL differs from the pre-registered model_id")
    base = os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    api_key = os.environ.get("DOUBAO_API_KEY")
    if not api_key:
        raise SystemExit("DOUBAO_API_KEY is missing")
    if prereg["input_order"] != ["global", "detail"]:
        raise SystemExit("runner only supports the pre-registered global,detail order")

    samples = manifest["samples"]
    if args.samples:
        requested = [value.strip() for value in args.samples.split(",") if value.strip()]
        if set(requested) != set(samples) or len(requested) != len(samples):
            raise SystemExit("--samples must list all 20 pre-registered samples exactly once")
        samples = requested

    if args.out_dir.exists() and any(args.out_dir.glob("*.json")):
        raise SystemExit(f"output directory already contains JSON files: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    endpoint = base.rstrip("/") + "/chat/completions"
    session = requests.Session()
    run_started_at = utc_now()
    run_started = time.perf_counter()
    run_meta = {
        "schema": "truckflow-multiscale-run-v1",
        "status": "running",
        "started_at": run_started_at,
        "finished_at": None,
        "command_contract": (
            "one primary request per sample; transport retry policy frozen in preregistration; "
            "schema-invalid responses fail without resampling"
        ),
        "model_id": model_id,
        "endpoint": endpoint,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "input_order": prereg["input_order"],
        "prompt_file": str(args.prompt.relative_to(ROOT)).replace("\\", "/"),
        "prompt_sha256": sha256_file(args.prompt),
        "manifest_file": str(args.manifest.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": sha256_file(args.manifest),
        "preregistration_file": str(args.preregistration.relative_to(ROOT)).replace("\\", "/"),
        "preregistration_sha256": sha256_file(args.preregistration),
        "sample_count": len(samples),
        "primary_requests": len(samples),
        "images_per_primary_request": 2,
        "samples": {},
    }
    write_json(args.out_dir / "_run.json", run_meta)

    for sample_index, sample_id in enumerate(samples, start=1):
        entry = manifest["images"][sample_id]
        global_path = ROOT / entry["global"]
        detail_path = ROOT / entry["detail"]
        if sha256_file(global_path) != entry["global_sha256"]:
            raise SystemExit(f"{sample_id}: global image hash mismatch")
        if sha256_file(detail_path) != entry["detail_sha256"]:
            raise SystemExit(f"{sample_id}: detail image hash mismatch")

        payload = {
            "model": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri(global_path)}},
                        {"type": "image_url", "image_url": {"url": data_uri(detail_path)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        sample_started_at = utc_now()
        sample_started = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        selected_attempt: dict[str, Any] | None = None
        success_body: dict[str, Any] | None = None

        for attempt_number in range(1, MAX_ATTEMPTS + 1):
            record, body, retryable = request_once(
                session, endpoint, api_key, payload, attempt_number
            )
            attempts.append(record)
            if body is not None:
                selected_attempt = record
                success_body = body
                break
            if record.get("http_status") not in RETRY_STATUS and retryable is False:
                break
            if attempt_number < MAX_ATTEMPTS:
                time.sleep(2 ** attempt_number)

        record: dict[str, Any] = {
            "schema": "truckflow-multiscale-sample-v1",
            "sample_id": sample_id,
            "sample_index": sample_index,
            "started_at": sample_started_at,
            "finished_at": None,
            "wall_latency_s": None,
            "images": {
                "order": ["global", "detail"],
                "global": {
                    "path": str(global_path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": entry["global_sha256"],
                    "size": entry["global_size"],
                },
                "detail": {
                    "path": str(detail_path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": entry["detail_sha256"],
                    "size": entry["detail_size"],
                },
            },
            "request_metadata": {
                "model_id": model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "input_order": ["global", "detail"],
                "prompt_sha256": run_meta["prompt_sha256"],
            },
            "attempts": attempts,
            "transport_retry_count": max(0, len(attempts) - 1),
            "status": "failed",
            "failure_kind": None,
            "failure_reason": None,
            "finish_reason": None,
            "usage": None,
            "raw_text": None,
            "parsed": None,
            "raw_bbox_audit": [],
            "validation_errors": [],
            "output_audit": None,
        }

        if success_body is None:
            record["failure_kind"] = "transport"
            record["failure_reason"] = (
                attempts[-1].get("transport_error", "no successful HTTP response")
                if attempts
                else "no attempt"
            )
        else:
            content, finish_reason, content_error = extract_content_and_finish(success_body)
            record["finish_reason"] = finish_reason
            record["usage"] = success_body.get("usage")
            record["raw_text"] = content
            if content_error:
                record["failure_kind"] = "response"
                record["failure_reason"] = content_error
            elif finish_reason == "length":
                record["failure_kind"] = "truncated"
                record["failure_reason"] = "finish_reason is length"
            else:
                parsed, parse_error = parse_json(content)
                if parse_error:
                    record["failure_kind"] = "schema"
                    record["failure_reason"] = parse_error
                else:
                    errors, output_audit = validate_parsed(parsed)
                    record["parsed"] = parsed
                    record["raw_bbox_audit"] = (
                        boxes_to_full_pixels(parsed) if isinstance(parsed, dict) else []
                    )
                    record["validation_errors"] = errors
                    record["output_audit"] = output_audit
                    if errors:
                        record["failure_kind"] = "schema"
                        record["failure_reason"] = "; ".join(errors)
                    else:
                        record["status"] = "ok"

        record["finished_at"] = utc_now()
        record["wall_latency_s"] = round(time.perf_counter() - sample_started, 3)
        write_json(args.out_dir / f"{sample_id}.json", record)
        run_meta["samples"][sample_id] = {
            "file": f"{sample_id}.json",
            "status": record["status"],
            "failure_kind": record["failure_kind"],
            "transport_retry_count": record["transport_retry_count"],
            "wall_latency_s": record["wall_latency_s"],
            "usage": record["usage"],
        }
        write_json(args.out_dir / "_run.json", run_meta)
        predicted = None
        if record["parsed"] and isinstance(record["parsed"].get("counts"), dict):
            predicted = record["parsed"]["counts"].get("total")
        print(
            f"[{sample_index:02d}/{len(samples)}] {sample_id} "
            f"status={record['status']} total={predicted} "
            f"attempts={len(attempts)} latency={record['wall_latency_s']:.2f}s",
            flush=True,
        )

    run_meta["status"] = (
        "complete"
        if all(item["status"] == "ok" for item in run_meta["samples"].values())
        else "complete-with-failures"
    )
    run_meta["finished_at"] = utc_now()
    run_meta["total_wall_latency_s"] = round(time.perf_counter() - run_started, 3)
    run_meta["ok_samples"] = sum(
        item["status"] == "ok" for item in run_meta["samples"].values()
    )
    run_meta["failed_samples"] = len(samples) - run_meta["ok_samples"]
    run_meta["total_attempts"] = sum(
        len(json.loads((args.out_dir / f"{sample}.json").read_text(encoding="utf-8"))["attempts"])
        for sample in samples
    )
    write_json(args.out_dir / "_run.json", run_meta)
    print(
        f"run {run_meta['status']}: ok={run_meta['ok_samples']}/{len(samples)} "
        f"attempts={run_meta['total_attempts']} "
        f"wall={run_meta['total_wall_latency_s']:.2f}s",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--samples", help="Comma-separated; must still contain all 20 samples")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
