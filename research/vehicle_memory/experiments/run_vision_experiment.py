"""Run one frozen, budget-capped multimodal experiment with no retries."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


VM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VM_ROOT.parents[1]
EVIDENCE_ROOT = VM_ROOT / "evidence"
MAX_REQUESTS_THIS_ROUND = 40
PRINT_LOCK = threading.Lock()


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def data_uri(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/png" if suffix == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def resolve_model() -> dict[str, str]:
    base = os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    key = os.environ.get("DOUBAO_API_KEY", "")
    model = os.environ.get("DOUBAO_MODEL", "ep-20260828174616-dthpx")
    if not key:
        raise RuntimeError("DOUBAO_API_KEY is not configured")
    return {"base": base.rstrip("/"), "key": key, "model": model}


def images_for(config: dict[str, Any], sample: str) -> list[Path]:
    experiment_id = config["experiment_id"]
    if experiment_id == "dualscale_v1":
        manifest = read_json(REPO_ROOT / config["input_manifest"])
        row = next(item for item in manifest["samples"] if item["sample_id"] == sample)
        primary = REPO_ROOT / row["primary"]
        secondary = REPO_ROOT / row["secondary"]
        if sha256(primary) != row["primary_sha256"]:
            raise RuntimeError(f"primary input hash changed: {primary}")
        if sha256(secondary) != row["secondary_sha256"]:
            raise RuntimeError(f"secondary input hash changed: {secondary}")
        return [primary, secondary]
    if experiment_id == "component_assembly_v1":
        return [REPO_ROOT / "accuracy" / "crops" / f"{sample}_aisle.jpg"]
    raise RuntimeError(f"unsupported experiment: {experiment_id}")


def run_one(
    *,
    config: dict[str, Any],
    model_cfg: dict[str, str],
    prompt: str,
    prompt_hash: str,
    config_hash: str,
    frozen_commit: str,
    worktree_status: str,
    sample: str,
    out_path: Path,
) -> dict[str, Any]:
    images = images_for(config, sample)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for index, image in enumerate(images, start=1):
        content.append({"type": "text", "text": f"image {index}"})
        content.append({"type": "image_url", "image_url": {"url": data_uri(image)}})

    payload = {
        "model": model_cfg["model"],
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "messages": [{"role": "user", "content": content}],
    }
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    result: dict[str, Any] = {
        "schema": "truckflow-vision-experiment-run-v1",
        "experiment_id": config["experiment_id"],
        "sample_id": sample,
        "mechanism": config["mechanism"],
        "model": config["model"],
        "model_id": model_cfg["model"],
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "attempts": 1,
        "retry_policy": config["retry_policy"],
        "request_count": 1,
        "started_at_utc": started_at,
        "frozen_commit": frozen_commit,
        "worktree_status_at_start": worktree_status,
        "config_sha256": config_hash,
        "prompt_sha256": prompt_hash,
        "input_files": [str(path.relative_to(REPO_ROOT)).replace("\\", "/") for path in images],
        "input_sha256": [sha256(path) for path in images],
    }
    try:
        response = requests.post(
            model_cfg["base"] + "/chat/completions",
            headers={
                "Authorization": f"Bearer {model_cfg['key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
        result["status_code"] = response.status_code
        result["latency_s"] = round(time.perf_counter() - started, 3)
        response.raise_for_status()
        body = response.json()
        raw_text = body["choices"][0]["message"]["content"]
        if isinstance(raw_text, list):
            raw_text = "".join(
                part.get("text", "") for part in raw_text if isinstance(part, dict)
            )
        result.update(
            {
                "ok": True,
                "usage": body.get("usage"),
                "raw_text": raw_text,
                "parsed": extract_json(raw_text),
            }
        )
    except Exception as error:  # retain failures in the fixed denominator
        result["latency_s"] = round(time.perf_counter() - started, 3)
        result["ok"] = False
        result["error_type"] = type(error).__name__
        result["error"] = str(error)[:2000]
        response = getattr(error, "response", None)
        if response is not None:
            result["status_code"] = response.status_code
            result["response_text"] = response.text[:2000]
    write_json(out_path, result)
    with PRINT_LOCK:
        if result["ok"]:
            counts = result["parsed"].get("counts", {})
            print(
                f"{sample}: total={counts.get('total')} "
                f"vehicles={len(result['parsed'].get('vehicles', []))} "
                f"latency={result['latency_s']}s",
                flush=True,
            )
        else:
            print(f"{sample}: FAILED {result['error_type']} {result['error'][:120]}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    config_path = (REPO_ROOT / args.config).resolve()
    config = read_json(config_path)
    samples = list(config["samples"])
    if len(samples) != int(config["new_call_budget"]):
        raise RuntimeError("sample count must equal the frozen new-call budget")
    if len(samples) > MAX_REQUESTS_THIS_ROUND:
        raise RuntimeError("experiment exceeds the 40-request round cap")

    experiment_id = config["experiment_id"]
    out_dir = EVIDENCE_ROOT / experiment_id
    existing = [out_dir / f"{sample}.json" for sample in samples]
    if any(path.exists() for path in existing) and not args.force:
        raise RuntimeError(f"refusing to overwrite existing evidence in {out_dir}")

    prompt_path = REPO_ROOT / config["prompt_file"]
    prompt = prompt_path.read_text(encoding="utf-8")
    prompt_hash = sha256(prompt_path)
    config_hash = sha256(config_path)
    frozen_commit = git_value("rev-parse", "HEAD")
    worktree_status = git_value("status", "--porcelain")
    if worktree_status:
        raise RuntimeError("worktree must be clean before frozen model calls")
    model_cfg = resolve_model()
    started_at = datetime.now(timezone.utc).isoformat()

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=int(config["concurrency"])) as executor:
        futures = {
            executor.submit(
                run_one,
                config=config,
                model_cfg=model_cfg,
                prompt=prompt,
                prompt_hash=prompt_hash,
                config_hash=config_hash,
                frozen_commit=frozen_commit,
                worktree_status=worktree_status,
                sample=sample,
                out_path=out_dir / f"{sample}.json",
            ): sample
            for sample in samples
        }
        for future in as_completed(futures):
            results.append(future.result())

    ordered = [next(item for item in results if item["sample_id"] == sample) for sample in samples]
    succeeded = sum(bool(item["ok"]) for item in ordered)
    total_tokens = sum(
        int((item.get("usage") or {}).get("total_tokens") or 0) for item in ordered
    )
    manifest = {
        "schema": "truckflow-vision-experiment-manifest-v1",
        "experiment_id": experiment_id,
        "mechanism": config["mechanism"],
        "frozen_commit": frozen_commit,
        "config_sha256": config_hash,
        "prompt_sha256": prompt_hash,
        "model": config["model"],
        "model_id": model_cfg["model"],
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "concurrency": config["concurrency"],
        "retry_policy": config["retry_policy"],
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_budget": len(samples),
        "request_count": len(ordered),
        "successful_requests": succeeded,
        "failed_requests": len(ordered) - succeeded,
        "total_tokens": total_tokens,
        "latency_s_sum": round(sum(float(item["latency_s"]) for item in ordered), 3),
        "ordered_samples": samples,
        "run_files": [
            str((out_dir / f"{sample}.json").relative_to(REPO_ROOT)).replace("\\", "/")
            for sample in samples
        ],
        "forbidden_inputs": config["forbidden_inputs"],
    }
    write_json(out_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
