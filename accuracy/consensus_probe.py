"""Run the same aisle-crop counting prompt across several vision models.

The experiment intentionally keeps the existing ``model_probe`` request and
parse path. This runner adds resumable per-frame evidence files, explicit model
IDs, concurrency, and a manifest with token/latency totals.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import model_probe
import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = Path(r"D:\File\PROJECT\codex\codex-货车\codexcodex-货车\.env")
DEFAULT_OUT = ROOT / "accuracy" / "runs" / "consensus_v1"


MODEL_CONFIGS: dict[str, dict[str, str]] = {
    "doubao": {
        "base_env": "DOUBAO_BASE_URL",
        "key_env": "DOUBAO_API_KEY",
        "model_env": "DOUBAO_MODEL",
        "fallback_base": "https://ark.cn-beijing.volces.com/api/v3",
        "fallback_model": "ep-20260828174616-dthpx",
    },
    "aibox-deepseek-v4.1-flash": {
        "base_env": "AIBOX_BASE_URL",
        "key_env": "AIBOX_API_KEY",
        "model_env": "",
        "fallback_base": "https://aibox.richaibox.com:2078/v1",
        "fallback_model": "deepseek-v4.1-flash",
        "extra_payload": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "aibox-glm-5.3-flash": {
        "base_env": "AIBOX_BASE_URL",
        "key_env": "AIBOX_API_KEY",
        "model_env": "",
        "fallback_base": "https://aibox.richaibox.com:2078/v1",
        "fallback_model": "glm-5.3-flash",
        "extra_payload": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "zhipu": {
        "base_env": "ZHIPU_BASE_URL",
        "key_env": "ZHIPU_API_KEY",
        "model_env": "ZHIPU_MODEL",
        "fallback_base": "https://open.bigmodel.cn/api/paas/v4",
        "fallback_model": "glm-4.7",
    },
}


def sample_ids() -> list[str]:
    images = sorted((ROOT / "accuracy" / "crops").glob("*_aisle.jpg"))
    images = [path for path in images if "grid_aisle" not in path.name]
    return [path.stem.removesuffix("_aisle") for path in images]


def install_models(names: list[str]) -> None:
    for name in names:
        if name not in MODEL_CONFIGS:
            raise SystemExit(f"unknown model: {name}")
        cfg = MODEL_CONFIGS[name]
        key = os.environ.get(cfg["key_env"], "")
        if not key:
            raise SystemExit(f"missing environment variable {cfg['key_env']} for {name}")
        base = os.environ.get(cfg["base_env"]) or cfg["fallback_base"]
        model = (os.environ.get(cfg["model_env"]) if cfg["model_env"] else None) or cfg["fallback_model"]
        model_probe.MODELS[name] = {"base": base, "key": cfg["key_env"], "model": model}


def request_options(name: str) -> dict[str, Any]:
    return dict(MODEL_CONFIGS[name].get("extra_payload") or {})


def run_one(name: str, image: Path, out_path: Path, prompt: str, max_tokens: int, retries: int) -> dict[str, Any]:
    if out_path.exists():
        try:
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            if cached.get("ok"):
                cached["cached"] = True
                return cached
        except json.JSONDecodeError:
            pass

    result = probe_with_evidence(name, image.resolve(), prompt, max_tokens, retries=retries)
    result.update(
        {
            "sample_id": image.stem.removesuffix("_aisle"),
            "image": str(image.resolve()),
            "prompt_version": "truck-count-v1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def probe_with_evidence(
    name: str,
    image_path: Path,
    prompt: str,
    max_tokens: int,
    retries: int = 3,
) -> dict[str, Any]:
    """Same request/parse contract as model_probe.probe, with raw-body evidence."""

    cfg = model_probe.MODELS[name]
    api_key = os.environ.get(cfg["key"], "")
    if not api_key:
        return {"model": name, "ok": False, "error": f"missing {cfg['key']}"}

    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": model_probe.data_uri(image_path)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        **request_options(name),
    }
    started = time.perf_counter()
    last_error: dict[str, Any] | None = None
    for attempt in range(retries):
        body: dict[str, Any] | None = None
        choice: dict[str, Any] = {}
        content: Any = None
        reasoning: Any = None
        try:
            response = requests.post(
                cfg["base"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
            latency = round(time.perf_counter() - started, 2)
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            body = response.json()
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            base_evidence = {
                "model": name,
                "model_id": cfg["model"],
                "attempts": attempt + 1,
                "latency_s": latency,
                "usage": body.get("usage"),
                "finish_reason": choice.get("finish_reason"),
                "raw_text": content,
                "reasoning_text": reasoning[:8000] if isinstance(reasoning, str) else None,
                "raw_body": body,
            }
            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    f"empty message.content (finish_reason={choice.get('finish_reason')}, "
                    f"reasoning_chars={len(reasoning) if isinstance(reasoning, str) else 0})"
                )
            parsed = model_probe.extract_json(content)
            return {**base_evidence, "ok": True, "parsed": parsed}
        except Exception as exc:  # keep raw failure as evidence
            status = getattr(getattr(exc, "response", None), "status_code", None)
            text = getattr(getattr(exc, "response", None), "text", "")
            last_error = {
                "model": name,
                "model_id": cfg["model"],
                "attempts": attempt + 1,
                "ok": False,
                "latency_s": round(time.perf_counter() - started, 2),
                "status": status,
                "error": f"{type(exc).__name__}: {exc}",
                "response_text": text[:2000],
                **(
                    {
                        "finish_reason": choice.get("finish_reason"),
                        "raw_text": content,
                        "reasoning_text": reasoning[:8000] if isinstance(reasoning, str) else None,
                        "raw_body": body,
                    }
                    if body is not None
                    else {}
                ),
            }
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last_error is not None
    return last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--models",
        default="doubao,aibox-deepseek-v4.1-flash,aibox-glm-5.3-flash",
    )
    parser.add_argument("--samples", default="", help="comma-separated sample ids")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    model_probe.load_env(args.env_path)
    names = [name.strip() for name in args.models.split(",") if name.strip()]
    install_models(names)
    ids = [value.strip() for value in args.samples.split(",") if value.strip()] or sample_ids()
    if args.limit:
        ids = ids[: args.limit]

    tasks = []
    for name in names:
        for sample_id in ids:
            image = ROOT / "accuracy" / "crops" / f"{sample_id}_aisle.jpg"
            if not image.exists():
                raise SystemExit(f"missing crop: {image}")
            tasks.append((name, image, args.out / "raw" / name / f"{sample_id}.json"))

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                run_one,
                name,
                image,
                out_path,
                model_probe.PROMPT,
                args.max_tokens,
                args.retries,
            ): (name, out_path)
            for name, image, out_path in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            name, _ = futures[future]
            result = future.result()
            with lock:
                results.append(result)
            if result.get("ok"):
                total = result.get("parsed", {}).get("counts", {}).get("total")
                print(f"{name:<30} {result['sample_id']:<14} total={total} {result['latency_s']}s", flush=True)
            else:
                print(f"{name:<30} {result['sample_id']:<14} FAILED {result.get('error')}", flush=True)

    elapsed = round(time.perf_counter() - started, 2)
    manifest = {
        "schema": "truckflow-consensus-probe-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "models": {name: model_probe.MODELS[name]["model"] for name in names},
        "samples": ids,
        "prompt_version": "truck-count-v1",
        "prompt_sha256": __import__("hashlib").sha256(model_probe.PROMPT.encode("utf-8")).hexdigest(),
        "request_options": {name: request_options(name) for name in names},
        "workers": args.workers,
        "wall_clock_s": elapsed,
        "results": len(results),
        "ok": sum(bool(item.get("ok")) for item in results),
        "failed": sum(not item.get("ok") for item in results),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"manifest_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
