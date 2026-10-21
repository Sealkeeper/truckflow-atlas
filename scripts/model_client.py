"""Thin OpenAI-compatible multimodal client with raw evidence retention."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def data_uri(image: Path) -> str:
    suffix = image.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/png" if suffix == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def model_config(name: str) -> dict[str, str]:
    prefix = name.upper()
    return {
        "base": os.environ.get(f"{prefix}_BASE_URL", ""),
        "key": os.environ.get(f"{prefix}_API_KEY", ""),
        "model": os.environ.get(f"{prefix}_MODEL", ""),
    }


def probe(
    model: str,
    image_paths: list[Path],
    prompt: str,
    *,
    max_tokens: int = 3000,
    timeout_s: int = 240,
) -> dict[str, Any]:
    cfg = model_config(model)
    if not cfg["base"] or not cfg["key"] or not cfg["model"]:
        return {"model": model, "ok": False, "error": f"incomplete {model.upper()} configuration"}
    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": data_uri(path)}} for path in image_paths
    ]
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    started = time.perf_counter()
    try:
        response = requests.post(
            cfg["base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_s,
        )
        latency = round(time.perf_counter() - started, 3)
        response.raise_for_status()
        body = response.json()
        raw = body["choices"][0]["message"]["content"]
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
        parsed = extract_json(raw)
        return {
            "model": model,
            "model_id": cfg["model"],
            "ok": True,
            "latency_s": latency,
            "request_id": body.get("id"),
            "usage": body.get("usage"),
            "parsed": parsed,
            "raw_text": raw,
        }
    except Exception as exc:  # preserve service failures as experiment evidence
        response = getattr(exc, "response", None)
        return {
            "model": model,
            "model_id": cfg["model"],
            "ok": False,
            "latency_s": round(time.perf_counter() - started, 3),
            "status": getattr(response, "status_code", None),
            "error": f"{type(exc).__name__}: {exc}",
            "response_text": getattr(response, "text", "")[:3000],
        }
