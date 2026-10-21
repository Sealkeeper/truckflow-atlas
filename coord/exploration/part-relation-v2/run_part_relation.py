#!/usr/bin/env python3
"""Roof-only top-surface relation prototype.

Mechanism: a VLM enumerates locatable roof/top observations and judges pairwise
top continuity, top-level separation, or physical-composition uncertainty.
Local code builds top units from same_top_surface edges and reports a point count
only when no composition ambiguity remains; otherwise it reports [min,max].

Stages:
  prepare   deterministic overview/far-detail images and frozen manifest; no API
  run       one VLM call per pre-registered sample; raw responses and attempts preserved
  evaluate  offline assembly + metrics; truth is read only after calls
  viz       roof boxes, top-unit colors and top junction evidence
  all       prepare, run, evaluate, viz

The script never prints or stores the API key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


SESS = Path(__file__).resolve().parent
ROOT = SESS.parents[1]
PUBLIC = ROOT / "all-sessions-can-see"
PUB = PUBLIC / "coord" / "exploration" / "part-relation-v2"
README = Path(r"D:/File/PROJECT/数据底座/数据底座-货车/README.md")
TRUTH = PUBLIC / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
AISLE_DIR = PUBLIC / "coord" / "exploration" / "single-pass" / "inputs" / "aisle"
B_RAW_DIR = PUBLIC / "coord" / "exploration" / "single-pass" / "raw" / "B_aisle"
FRAMES_DIR = PUBLIC / "assets" / "frames"

MODEL = "doubao-seed-2-1-lite-260915"
TEMPERATURE = 0
MAX_TOKENS = 12000
TIMEOUT_S = 300
MAX_TRANSPORT_RETRIES = 1
# Omitted deliberately: the official SDK exposes thinking.type, but exact
# support on this Lite model has not been independently established for this
# request shape. The 4-call budget does not allow a separate probe. Report
# observed reasoning tokens instead of claiming field-level support.
THINKING = None

FAR_CROP = {"x0": 0.06, "y0": 0.0, "x1": 0.94, "y1": 0.56, "scale": 1.6}

# Pre-registered before any paid call. Role text is for the experiment record,
# never for the model prompt.
SAMPLES = [
    {
        "sample_id": "south_2100",
        "camera": "south",
        "time": 2100,
        "role": "stable B overcount (4 vs truth 3); prior reports describe cab/trailer split, "
        "but B r1 box audit shows the extra 4th unit is a far/background truck",
    },
    {
        "sample_id": "south_300",
        "camera": "south",
        "time": 300,
        "role": "B r1 overcount 5 vs truth 4; B box 5 is a trailer-only duplicate of the foreground trailer",
    },
    {
        "sample_id": "north_5",
        "camera": "north",
        "time": 5,
        "role": "B unstable 5/4/3 vs truth 5; far adjacent cargo tops, gap-versus-merge target",
    },
    {
        "sample_id": "north_600",
        "camera": "north",
        "time": 600,
        "role": "B stable 4/4/4 vs truth 4; far-cargo preservation control",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path(r"C:/Windows/Fonts/segoeui.ttf"),
        Path(r"C:/Windows/Fonts/arial.ttf"),
        Path(r"C:/Windows/Fonts/msyh.ttc"),
    ):
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 22) -> None:
    draw.text(xy, text, font=load_font(size), fill=(255, 240, 0), stroke_width=3, stroke_fill=(0, 0, 0))


def draw_grid(im: Image.Image, border_label: str) -> Image.Image:
    base = im.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = base.size
    for i in range(1, 10):
        x = round(w * i / 10)
        y = round(h * i / 10)
        d.line([(x, 0), (x, h)], fill=(0, 255, 255, 95), width=2)
        d.line([(0, y), (w, y)], fill=(0, 255, 255, 95), width=2)
    out = Image.alpha_composite(base, layer).convert("RGB")
    d2 = ImageDraw.Draw(out)
    for i in range(1, 10):
        x = round(w * i / 10)
        y = round(h * i / 10)
        draw_label(d2, (min(max(x + 3, 0), w - 60), 5), f"{i/10:.1f}", 20)
        draw_label(d2, (4, min(max(y + 2, 0), h - 28)), f"{i/10:.1f}", 20)
    draw_label(d2, (8, h - 34), border_label, 20)
    return out


def prepare_inputs() -> dict[str, Any]:
    SESS.joinpath("inputs").mkdir(parents=True, exist_ok=True)
    PUB.mkdir(parents=True, exist_ok=True)
    prompt_path = SESS / "prompt_roof_relation.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    prompt_sha = sha256_bytes(prompt.encode("utf-8"))

    records: list[dict[str, Any]] = []
    for sample in SAMPLES:
        sid = sample["sample_id"]
        source = AISLE_DIR / f"{sid}.jpg"
        if not source.exists():
            raise FileNotFoundError(source)
        im = Image.open(source).convert("RGB")
        w, h = im.size
        far_px = (
            round(FAR_CROP["x0"] * w),
            round(FAR_CROP["y0"] * h),
            round(FAR_CROP["x1"] * w),
            round(FAR_CROP["y1"] * h),
        )

        overview = draw_grid(im, "IMAGE A: AISLE OVERVIEW (grid is a locator only)")
        od = ImageDraw.Draw(overview)
        od.rectangle(far_px, outline=(255, 220, 0), width=6)
        draw_label(od, (far_px[0] + 8, far_px[1] + 8), "FAR DETAIL -> IMAGE B", 24)
        overview_path = SESS / "inputs" / f"{sid}_overview.jpg"
        overview.save(overview_path, format="JPEG", quality=92, subsampling=0)

        crop = im.crop(far_px)
        far_size = (
            max(1, round(crop.width * FAR_CROP["scale"])),
            max(1, round(crop.height * FAR_CROP["scale"])),
        )
        far = crop.resize(far_size, Image.Resampling.LANCZOS)
        far = draw_grid(far, "IMAGE B: 1.6x FAR DETAIL OF THE YELLOW BOX IN IMAGE A")
        fd = ImageDraw.Draw(far)
        fd.rectangle((0, 0, far.width - 1, far.height - 1), outline=(255, 220, 0), width=6)
        far_path = SESS / "inputs" / f"{sid}_far.jpg"
        far.save(far_path, format="JPEG", quality=92, subsampling=0)

        records.append(
            {
                **sample,
                "source_aisle": str(source.relative_to(PUBLIC)),
                "source_aisle_sha256": sha256_file(source),
                "source_size": [w, h],
                "overview": {
                    "path": str(overview_path.relative_to(SESS)),
                    "sha256": sha256_file(overview_path),
                    "size": list(overview.size),
                },
                "far": {
                    "path": str(far_path.relative_to(SESS)),
                    "sha256": sha256_file(far_path),
                    "size": list(far.size),
                    "crop_overview_px": list(far_px),
                    "crop_overview_norm": [FAR_CROP["x0"], FAR_CROP["y0"], FAR_CROP["x1"], FAR_CROP["y1"]],
                    "scale": FAR_CROP["scale"],
                },
            }
        )

    frozen = {
        "schema": "roof-relation-v2-input-freeze",
        "created_at": now_iso(),
        "mechanism": "roof-only top observations + top continuity/gap/uncertainty edges + deterministic top units and count range",
        "model": MODEL,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "thinking": THINKING,
        "thinking_source": "official volcengine/volcengine-python-sdk types/shared_params/thinking.py Literal enabled|disabled|auto; this experiment omits the field because exact Lite support for this request shape was not independently verified; observed usage is reported instead",
        "session_reasoning": "high per ROOF_ONLY_STEERING.md; current model unchanged",
        "timeout_s": TIMEOUT_S,
        "workers": 1,
        "budget": {
            "main_calls": len(SAMPLES),
            "images_per_call": 2,
            "http_attempts_max": len(SAMPLES) + MAX_TRANSPORT_RETRIES,
            "transport_retry_max": MAX_TRANSPORT_RETRIES,
            "schema_retry": 0,
            "same_image_reask": False,
        },
        "prompt_file": "prompt_roof_relation.txt",
        "prompt_sha256": prompt_sha,
        "far_crop": FAR_CROP,
        "credential_policy": "read only ARK_API_KEY= and ARK_BASE_URL= from data-base README at request time; never log values",
        "samples": records,
    }
    write_json(SESS / "frozen_inputs.json", frozen)
    write_json(PUB / "frozen_inputs.json", frozen)
    print(json.dumps({"prepared": [s["sample_id"] for s in records], "prompt_sha256": prompt_sha}, ensure_ascii=False))
    return frozen


def load_credentials() -> tuple[str, str]:
    if not README.exists():
        raise FileNotFoundError(README)
    key = ""
    base = ""
    for line in README.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("ARK_API_KEY") and "=" in s:
            key = s.split("=", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("ARK_BASE_URL") and "=" in s:
            base = s.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or not base:
        raise RuntimeError("ARK_API_KEY/ARK_BASE_URL not found in data-base README")
    return key, base


def data_uri(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def endpoint(base: str) -> str:
    base = base.rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def run() -> None:
    frozen_path = SESS / "frozen_inputs.json"
    if not frozen_path.exists():
        raise RuntimeError("run prepare first")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    prompt_path = SESS / frozen["prompt_file"]
    prompt = prompt_path.read_text(encoding="utf-8")
    if sha256_bytes(prompt.encode("utf-8")) != frozen["prompt_sha256"]:
        raise RuntimeError("prompt changed after freeze")

    for rec in frozen["samples"]:
        for role in ("overview", "far"):
            p = SESS / rec[role]["path"]
            if sha256_file(p) != rec[role]["sha256"]:
                raise RuntimeError(f"input changed after freeze: {p}")

    key, base = load_credentials()
    api_url = endpoint(base)
    attempts_log: list[dict[str, Any]] = []
    transport_retries_used = 0
    consecutive_transport_failures = 0

    for rec in frozen["samples"]:
        sid = rec["sample_id"]
        raw_path = SESS / "raw" / f"{sid}.json"
        if raw_path.exists():
            print(json.dumps({"sample_id": sid, "status": "skipped_existing_raw"}, ensure_ascii=False))
            continue

        overview = SESS / rec["overview"]["path"]
        far = SESS / rec["far"]["path"]
        payload = {
            "model": frozen["model"],
            "temperature": frozen["temperature"],
            "max_tokens": frozen["max_tokens"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri(overview)}},
                        {"type": "image_url", "image_url": {"url": data_uri(far)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        if frozen.get("thinking") is not None:
            payload["thinking"] = frozen["thinking"]

        attempts: list[dict[str, Any]] = []
        final_body: dict[str, Any] | None = None
        final_text: str | None = None
        final_error: str | None = None
        final_latency = 0.0
        retried = False

        while True:
            started = time.perf_counter()
            status_code = None
            body = None
            error_text = None
            try:
                resp = requests.post(
                    api_url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=(20, TIMEOUT_S),
                )
                elapsed = round(time.perf_counter() - started, 3)
                status_code = resp.status_code
                if status_code == 200:
                    body = resp.json()
                else:
                    error_text = resp.text[:2000]
            except Exception as exc:
                elapsed = round(time.perf_counter() - started, 3)
                error_text = f"{type(exc).__name__}: {exc}"

            attempt_rec = {
                "attempt": len(attempts) + 1,
                "started_at": now_iso(),
                "status_code": status_code,
                "elapsed_s": elapsed,
                "error_excerpt": error_text,
                "response_sha256": sha256_bytes(json.dumps(body, ensure_ascii=False).encode("utf-8")) if body is not None else None,
            }
            attempts.append(attempt_rec)
            attempts_log.append({"sample_id": sid, **attempt_rec})
            final_latency = elapsed

            retryable = body is None and (
                status_code is None or status_code in {408, 429, 500, 502, 503, 504}
            )
            if body is not None:
                final_body = body
                try:
                    content = body["choices"][0]["message"]["content"]
                    if isinstance(content, list):
                        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                    final_text = content
                except Exception as exc:
                    final_error = f"response_shape: {type(exc).__name__}: {exc}"
                break
            if retryable and transport_retries_used < MAX_TRANSPORT_RETRIES and not retried:
                transport_retries_used += 1
                retried = True
                time.sleep(4)
                continue
            final_error = error_text or f"HTTP {status_code}"
            break

        parsed = None
        parse_error = None
        if final_text is not None and final_error is None:
            try:
                parsed = extract_json(final_text)
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"

        raw = {
            "schema": "roof-relation-v2-raw",
            "sample_id": sid,
            "camera": rec["camera"],
            "time": rec["time"],
            "model": frozen["model"],
            "temperature": frozen["temperature"],
            "max_tokens": frozen["max_tokens"],
            "thinking_requested": frozen.get("thinking"),
            "prompt_sha256": frozen["prompt_sha256"],
            "inputs": [
                {"role": "overview", "path": rec["overview"]["path"], "sha256": rec["overview"]["sha256"]},
                {"role": "far", "path": rec["far"]["path"], "sha256": rec["far"]["sha256"]},
            ],
            "http_attempts": attempts,
            "response": final_body,
            "content": final_text,
            "parsed": parsed,
            "parse_error": parse_error,
            "usage": (final_body or {}).get("usage") or {},
            "latency_s": final_latency,
            "failure": final_error,
        }
        write_json(raw_path, raw)

        if final_error and final_body is None:
            consecutive_transport_failures += 1
        else:
            consecutive_transport_failures = 0
        print(
            json.dumps(
                {
                    "sample_id": sid,
                    "status": "ok" if final_error is None and parse_error is None else "failure",
                    "http_attempts": len(attempts),
                    "latency_s": final_latency,
                    "parse_error": parse_error,
                    "failure": final_error,
                },
                ensure_ascii=False,
            )
        )
        if consecutive_transport_failures >= 2:
            print(json.dumps({"stopped": "two_consecutive_transport_failures"}, ensure_ascii=False))
            break

    write_json(SESS / "attempts.json", {"schema": "roof-relation-v2-attempts", "written_at": now_iso(), "attempts": attempts_log})


class UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


VALID_KINDS = {"cab_roof", "cargo_roof", "trailer_roof", "open_top", "mixed_top", "unknown"}
VALID_STATES = {"closed", "open", "partial", "occluded", "unknown"}
VALID_RELATIONS = {"same_top_surface", "separate_top_units", "composition_unknown", "ambiguous"}
CARGO_KINDS = {"cargo_roof", "trailer_roof", "open_top"}
CAB_KINDS = {"cab_roof"}


def valid_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
        return False
    x1, y1, x2, y2 = value
    return 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0


def valid_polygon(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 3:
        return False
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            return False
        if not all(isinstance(x, (int, float)) and math.isfinite(x) and 0.0 <= x <= 1.0 for x in point):
            return False
    return True


def map_far_bbox(bbox: list[float], rec: dict[str, Any]) -> list[float]:
    x0, y0, x1, y1 = rec["far"]["crop_overview_norm"]
    a, b, c, d = bbox
    return [x0 + a * (x1 - x0), y0 + b * (y1 - y0), x0 + c * (x1 - x0), y0 + d * (y1 - y0)]


def map_far_polygon(poly: list[list[float]], rec: dict[str, Any]) -> list[list[float]]:
    x0, y0, x1, y1 = rec["far"]["crop_overview_norm"]
    return [[x0 + p[0] * (x1 - x0), y0 + p[1] * (y1 - y0)] for p in poly]


def bbox_iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def union_bbox(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def assemble(parsed: dict[str, Any] | None, rec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "parsed_ok": parsed is not None,
        "schema_warnings": [],
        "tops": [],
        "relations": [],
        "top_units": [],
        "count_point": None,
        "count_min": None,
        "count_max": None,
        "resolved": False,
        "review_required": True,
        "review_reasons": [],
        "relation_stats": {},
        "ambiguous_groups": [],
        "certain_unit_count": None,
        "possible_duplicate_top_units": [],
    }
    if not isinstance(parsed, dict):
        result["review_reasons"].append("no_parsed_json")
        return result

    tops_raw = parsed.get("tops")
    if not isinstance(tops_raw, list):
        result["review_reasons"].append("missing_tops_list")
        return result

    tops: dict[str, dict[str, Any]] = {}
    for idx, t in enumerate(tops_raw):
        if not isinstance(t, dict):
            result["schema_warnings"].append(f"top_{idx}_not_object")
            continue
        tid = str(t.get("top_id", "")).strip()
        if not tid or tid in tops:
            result["schema_warnings"].append(f"invalid_or_duplicate_top_id:{tid or idx}")
            continue
        view = t.get("view", "overview")
        if view not in {"overview", "far"}:
            result["schema_warnings"].append(f"{tid}_invalid_view:{view}")
            view = "overview"
        bbox = t.get("roof_bbox")
        locatable = bool(t.get("locatable", True))
        bbox_ok = valid_bbox(bbox)
        if not bbox_ok:
            locatable = False
            result["schema_warnings"].append(f"{tid}_invalid_roof_bbox")
        mapped = map_far_bbox(bbox, rec) if bbox_ok and view == "far" else (list(bbox) if bbox_ok else None)

        poly = t.get("roof_polygon", [])
        poly_ok = valid_polygon(poly)
        if poly and not poly_ok:
            result["schema_warnings"].append(f"{tid}_invalid_roof_polygon")
            poly = []
        mapped_poly = map_far_polygon(poly, rec) if poly_ok and view == "far" else (poly if poly_ok else [])

        kind = t.get("kind", "unknown")
        if kind not in VALID_KINDS:
            result["schema_warnings"].append(f"{tid}_invalid_kind:{kind}")
            kind = "unknown"
        state = t.get("top_state", "unknown")
        if state not in VALID_STATES:
            result["schema_warnings"].append(f"{tid}_invalid_top_state:{state}")
            state = "unknown"
        tops[tid] = {
            "top_id": tid,
            "view": view,
            "roof_bbox_view": list(bbox) if bbox_ok else None,
            "roof_bbox_overview": mapped,
            "roof_polygon": mapped_poly,
            "kind": kind,
            "top_state": state,
            "locatable": locatable,
            "visible_evidence": str(t.get("visible_evidence", ""))[:600],
        }

    result["tops"] = list(tops.values())
    valid_ids = [tid for tid, t in tops.items() if t["locatable"] and t["roof_bbox_overview"] is not None]
    uf = UnionFind(valid_ids)
    relations: list[dict[str, Any]] = []
    separate_edges: list[tuple[str, str]] = []
    ambiguity_edges: list[tuple[str, str]] = []
    relation_top_ids: set[str] = set()

    for idx, r in enumerate(parsed.get("relations") or []):
        if not isinstance(r, dict):
            result["schema_warnings"].append(f"relation_{idx}_not_object")
            continue
        a, b = str(r.get("a", "")).strip(), str(r.get("b", "")).strip()
        rel = r.get("relation")
        if a not in tops or b not in tops or a == b or rel not in VALID_RELATIONS:
            result["schema_warnings"].append(f"relation_{idx}_invalid:{a}/{b}/{rel}")
            continue
        junction = r.get("junction_bbox")
        junction_ok = valid_bbox(junction)
        if not junction_ok:
            result["schema_warnings"].append(f"relation_{idx}_invalid_junction")
        gap = r.get("gap_px", None)
        if not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap < 0:
            gap = None

        # Conservative semantic rule: a cab roof and a cargo/trailer roof are
        # distinct top units but top-only evidence cannot decide physical
        # composition. Do not silently turn that into "two vehicles".
        kinds = {tops[a]["kind"], tops[b]["kind"]}
        if rel == "separate_top_units" and kinds & CAB_KINDS and kinds & CARGO_KINDS:
            rel = "composition_unknown"
            result["schema_warnings"].append(f"relation_{idx}_cab_cargo_reinterpreted_as_composition_unknown")

        rec_rel = {
            "a": a,
            "b": b,
            "relation": rel,
            "junction_bbox": list(junction) if junction_ok else None,
            "gap_px": gap,
            "evidence": str(r.get("evidence", ""))[:800],
            "confidence": r.get("confidence") if isinstance(r.get("confidence"), (int, float)) else None,
        }
        relations.append(rec_rel)
        relation_top_ids.update([a, b])
        if a in valid_ids and b in valid_ids:
            if rel == "same_top_surface":
                uf.union(a, b)
            elif rel == "separate_top_units":
                separate_edges.append((a, b))
            else:
                ambiguity_edges.append((a, b))

    result["relations"] = relations
    conflicts: list[dict[str, Any]] = []
    for a, b in separate_edges:
        if uf.find(a) == uf.find(b):
            conflicts.append({"a": a, "b": b, "reason": "separate_edge_inside_same_top_surface"})

    components: dict[str, list[str]] = {}
    for tid in valid_ids:
        components.setdefault(uf.find(tid), []).append(tid)

    top_units: list[dict[str, Any]] = []
    top_to_unit: dict[str, str] = {}
    for ui, tids in enumerate(components.values(), start=1):
        uid = f"U{ui}"
        tlist = [tops[t] for t in tids]
        boxes = [t["roof_bbox_overview"] for t in tlist if t["roof_bbox_overview"]]
        top_units.append(
            {
                "top_unit_id": uid,
                "top_ids": sorted(tids),
                "kinds": sorted({t["kind"] for t in tlist}),
                "top_states": sorted({t["top_state"] for t in tlist}),
                "roof_bbox_overview": union_bbox(boxes),
                "locatable": all(t["locatable"] for t in tlist),
            }
        )
        for t in tids:
            top_to_unit[t] = uid
    result["top_units"] = top_units

    # Ambiguity graph over top units. min merges all composition-unknown edges;
    # max keeps every top unit separate. A point count is emitted only when the
    # ambiguity graph has no edges and no other review blocker exists.
    unit_ids = [u["top_unit_id"] for u in top_units]
    uf_amb = UnionFind(unit_ids)
    ambiguity_unit_edges: list[tuple[str, str]] = []
    for a, b in ambiguity_edges:
        if a in top_to_unit and b in top_to_unit:
            ua, ub = top_to_unit[a], top_to_unit[b]
            if ua != ub:
                ambiguity_unit_edges.append((ua, ub))
                uf_amb.union(ua, ub)
    amb_components: dict[str, list[str]] = {}
    for uid in unit_ids:
        amb_components.setdefault(uf_amb.find(uid), []).append(uid)
    result["ambiguous_groups"] = [
        {"unit_ids": sorted(v), "size": len(v)} for v in amb_components.values() if len(v) > 1
    ]
    certain_units = [u["top_unit_id"] for u in top_units if not any(u["top_unit_id"] in e for e in ambiguity_unit_edges)]
    result["certain_unit_count"] = len(certain_units)
    result["count_max"] = len(top_units)
    result["count_min"] = len(amb_components) if top_units else 0

    if not top_units:
        result["review_reasons"].append("no_locatable_tops")
    if len(tops) > 1 and not relations:
        result["review_reasons"].append("no_relations_for_multiple_tops")
    if ambiguity_unit_edges:
        result["review_reasons"].append(f"composition_ambiguity_edges:{len(ambiguity_unit_edges)}")
    if conflicts:
        result["review_reasons"].append(f"relation_conflicts:{len(conflicts)}")
    if any(not t["locatable"] for t in tops.values()):
        result["review_reasons"].append("unlocatable_tops")
    if any(t["kind"] == "unknown" or t["top_state"] in {"unknown", "occluded"} for t in tops.values()):
        result["review_reasons"].append("unknown_or_occluded_top")
    if isinstance(parsed.get("unresolved"), list) and parsed["unresolved"]:
        result["review_reasons"].append(f"model_unresolved:{len(parsed['unresolved'])}")
    if result["schema_warnings"]:
        result["review_reasons"].append(f"schema_warnings:{len(result['schema_warnings'])}")

    # Compare model-declared top-unit hypotheses with the deterministic units.
    model_units = parsed.get("top_unit_hypotheses")
    model_sets: set[frozenset[str]] = set()
    if isinstance(model_units, list):
        for ent in model_units:
            if isinstance(ent, dict) and isinstance(ent.get("top_ids"), list):
                ids = [str(x) for x in ent["top_ids"] if str(x) in tops]
                if ids:
                    model_sets.add(frozenset(ids))
    component_sets = {frozenset(u["top_ids"]) for u in top_units}
    result["model_unit_count"] = len(model_sets)
    result["model_unit_consistent"] = model_sets == component_sets
    if model_sets and not result["model_unit_consistent"]:
        result["review_reasons"].append("model_top_unit_hypotheses_inconsistent")

    # Geometry-only duplicate diagnostic; never merges.
    for i, ea in enumerate(top_units):
        for eb in top_units[i + 1 :]:
            if not ea["roof_bbox_overview"] or not eb["roof_bbox_overview"]:
                continue
            iou = bbox_iou(ea["roof_bbox_overview"], eb["roof_bbox_overview"])
            if iou >= 0.5:
                result["possible_duplicate_top_units"].append(
                    {"unit_a": ea["top_unit_id"], "unit_b": eb["top_unit_id"], "bbox_iou": round(iou, 4)}
                )
    if result["possible_duplicate_top_units"]:
        result["review_reasons"].append("possible_duplicate_top_units")

    result["review_required"] = bool(result["review_reasons"])
    result["resolved"] = not result["review_reasons"] and result["count_max"] is not None
    result["count_point"] = result["count_max"] if result["resolved"] else None
    result["relation_stats"] = {
        "total": len(relations),
        "same_top_surface": sum(1 for r in relations if r["relation"] == "same_top_surface"),
        "separate_top_units": sum(1 for r in relations if r["relation"] == "separate_top_units"),
        "composition_unknown": sum(1 for r in relations if r["relation"] == "composition_unknown"),
        "ambiguous": sum(1 for r in relations if r["relation"] == "ambiguous"),
        "with_junction": sum(1 for r in relations if r["junction_bbox"]),
        "with_gap_px": sum(1 for r in relations if r["gap_px"] is not None),
    }
    result["unknown_composition_share"] = (
        len(ambiguity_unit_edges) / len(top_units) if top_units else None
    )
    return result


def load_raw(sid: str) -> dict[str, Any] | None:
    p = SESS / "raw" / f"{sid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def truth_counts() -> dict[str, int]:
    data = json.loads(TRUTH.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for sample in data["samples"]:
        t = sample["time"]
        out[f"north_{t}"] = sample["camera_counts"]["north"]
        out[f"south_{t}"] = sample["camera_counts"]["south"]
    return out


def b_counts(sid: str) -> list[int | None]:
    out: list[int | None] = []
    for run in ("r1", "r2", "r3"):
        p = B_RAW_DIR / run / f"{sid}.json"
        if not p.exists():
            out.append(None)
            continue
        j = json.loads(p.read_text(encoding="utf-8"))
        out.append(len(j.get("vehicles") or []))
    return out


def evaluate() -> dict[str, Any]:
    frozen = json.loads((SESS / "frozen_inputs.json").read_text(encoding="utf-8"))
    truth = truth_counts()
    rows: list[dict[str, Any]] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    attempts_total = 0
    latencies: list[float] = []

    for rec in frozen["samples"]:
        sid = rec["sample_id"]
        raw = load_raw(sid)
        if raw is None:
            rows.append(
                {
                    "sample_id": sid,
                    "truth": truth.get(sid),
                    "b_counts": b_counts(sid),
                    "count_point": None,
                    "count_min": None,
                    "count_max": None,
                    "resolved": False,
                    "exact_point": False,
                    "range_contains_truth": False,
                    "valid": False,
                    "failure": "missing_raw",
                }
            )
            continue
        asm = assemble(raw.get("parsed"), rec)
        usage = raw.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        usage_totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        usage_totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        usage_totals["total_tokens"] += int(usage.get("total_tokens") or 0)
        usage_totals["reasoning_tokens"] += int(details.get("reasoning_tokens") or 0)
        attempts_total += len(raw.get("http_attempts") or [])
        if isinstance(raw.get("latency_s"), (int, float)):
            latencies.append(float(raw["latency_s"]))

        truth_n = truth.get(sid)
        point = asm.get("count_point")
        cmin = asm.get("count_min")
        cmax = asm.get("count_max")
        resolved = bool(asm.get("resolved"))
        exact_point = bool(resolved and point is not None and point == truth_n)
        range_ok = bool(cmin is not None and cmax is not None and truth_n is not None and cmin <= truth_n <= cmax)
        rows.append(
            {
                "sample_id": sid,
                "camera": rec["camera"],
                "time": rec["time"],
                "role": rec["role"],
                "truth": truth_n,
                "b_counts": b_counts(sid),
                "count_point": point,
                "count_min": cmin,
                "count_max": cmax,
                "resolved": resolved,
                "exact_point": exact_point,
                "range_contains_truth": range_ok,
                "valid": raw.get("failure") is None and raw.get("parse_error") is None,
                "failure": raw.get("failure") or raw.get("parse_error"),
                "review_required": asm.get("review_required"),
                "review_reasons": asm.get("review_reasons"),
                "relation_stats": asm.get("relation_stats"),
                "tops": len(asm.get("tops") or []),
                "top_units": len(asm.get("top_units") or []),
                "top_units_detail": asm.get("top_units"),
                "relation_detail": asm.get("relations"),
                "ambiguous_groups": asm.get("ambiguous_groups"),
                "certain_unit_count": asm.get("certain_unit_count"),
                "schema_warnings": asm.get("schema_warnings"),
                "possible_duplicate_top_units": asm.get("possible_duplicate_top_units"),
                "model_unit_consistent": asm.get("model_unit_consistent"),
                "unknown_composition_share": asm.get("unknown_composition_share"),
                "latency_s": raw.get("latency_s"),
                "usage": usage,
                "http_attempts": len(raw.get("http_attempts") or []),
                "parse_error": raw.get("parse_error"),
            }
        )

    valid_rows = [r for r in rows if r["valid"]]
    resolved_rows = [r for r in valid_rows if r["resolved"]]
    exact_resolved = sum(1 for r in resolved_rows if r["exact_point"])
    mae_resolved = (
        sum(abs(r["count_point"] - r["truth"]) for r in resolved_rows) / len(resolved_rows)
        if resolved_rows
        else None
    )
    under = sum(1 for r in resolved_rows if r["count_point"] < r["truth"])
    over = sum(1 for r in resolved_rows if r["count_point"] > r["truth"])
    range_ok = sum(1 for r in valid_rows if r["range_contains_truth"])
    lat_sorted = sorted(latencies)
    p95 = None
    if lat_sorted:
        p95 = lat_sorted[max(0, math.ceil(0.95 * len(lat_sorted)) - 1)]

    metrics = {
        "schema": "roof-relation-v2-metrics",
        "generated_at": now_iso(),
        "model": frozen["model"],
        "thinking": frozen["thinking"],
        "prompt_sha256": frozen["prompt_sha256"],
        "sample_count_fixed": len(rows),
        "valid_count": len(valid_rows),
        "resolved_count": len(resolved_rows),
        "resolved_coverage": round(len(resolved_rows) / len(rows), 4) if rows else None,
        "exact_point_count": exact_resolved,
        "exact_point_rate_resolved": round(exact_resolved / len(resolved_rows), 4) if resolved_rows else None,
        "mae_resolved": round(mae_resolved, 4) if mae_resolved is not None else None,
        "undercount_resolved": under,
        "overcount_resolved": over,
        "range_contains_truth_count": range_ok,
        "range_contains_truth_rate": round(range_ok / len(rows), 4) if rows else None,
        "range_metric_note": "range coverage is a calibration diagnostic, not a point-count accuracy",
        "failures": sum(1 for r in rows if not r["valid"]),
        "rows": rows,
        "cost": {
            "main_calls_requested": len(frozen["samples"]),
            "http_attempts": attempts_total,
            "usage_totals": usage_totals,
            "latency_total_s": round(sum(latencies), 3) if latencies else None,
            "latency_mean_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "latency_p95_s": p95,
            "images_per_call": 2,
        },
        "limits": [
            "4-frame diagnostic subset, not a 20-frame regression and not a generalization estimate",
            "truth file read only after all model calls; no truth or review annotation was sent to the model",
            "roof-only evidence; lower-body connections, plates, tires, lights and body text were excluded by prompt",
            "no complete roof/relation gold; top-unit correctness is audited qualitatively",
            "a count range containing truth is not the same as a correct point count",
        ],
    }
    write_json(SESS / "metrics.json", metrics)
    write_json(PUB / "metrics.json", metrics)
    print(
        json.dumps(
            {
                "valid_count": metrics["valid_count"],
                "resolved_count": metrics["resolved_count"],
                "exact_point_count": metrics["exact_point_count"],
                "range_contains_truth_count": metrics["range_contains_truth_count"],
                "failures": metrics["failures"],
            },
            ensure_ascii=False,
        )
    )
    return metrics


def unit_color(i: int) -> tuple[int, int, int]:
    palette = [
        (255, 80, 80),
        (80, 200, 255),
        (120, 255, 120),
        (255, 200, 60),
        (220, 120, 255),
        (255, 140, 40),
        (80, 255, 220),
        (255, 120, 200),
    ]
    return palette[i % len(palette)]


def relation_color(rel: str) -> tuple[int, int, int]:
    if rel == "same_top_surface":
        return (0, 255, 120)
    if rel == "separate_top_units":
        return (255, 60, 60)
    if rel == "composition_unknown":
        return (255, 220, 0)
    return (255, 140, 0)


def draw_top_graph(base_path: Path, asm: dict[str, Any], out_path: Path, full_frame: bool = False) -> None:
    im = Image.open(base_path).convert("RGB")
    d = ImageDraw.Draw(im)
    w, h = im.size
    top_to_unit: dict[str, int] = {}
    for i, ent in enumerate(asm.get("top_units") or []):
        for tid in ent["top_ids"]:
            top_to_unit[tid] = i

    def map_box(b: list[float]) -> list[float]:
        if not full_frame:
            return b
        return [350 + 520 * b[0], 960 * b[1], 350 + 520 * b[2], 960 * b[3]]

    for t in asm.get("tops") or []:
        b = t.get("roof_bbox_overview")
        if not b:
            continue
        bb = map_box(b)
        color = unit_color(top_to_unit.get(t["top_id"], 0))
        d.rectangle([bb[0] * w, bb[1] * h, bb[2] * w, bb[3] * h], outline=color, width=4)
        poly = t.get("roof_polygon") or []
        if len(poly) >= 3:
            pts = []
            for p in poly:
                pb = map_box([p[0], p[1], p[0], p[1]])
                pts.append((pb[0] * w, pb[1] * h))
            d.line(pts + [pts[0]], fill=color, width=3)
        d.text(
            (bb[0] * w + 4, bb[1] * h + 3),
            f"{t['top_id']} {t['kind']} U{top_to_unit.get(t['top_id'], 0)+1}",
            font=load_font(19),
            fill=color,
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
    for r in asm.get("relations") or []:
        jb = r.get("junction_bbox")
        if not jb:
            continue
        bb = map_box(jb)
        color = relation_color(r["relation"])
        d.rectangle([bb[0] * w, bb[1] * h, bb[2] * w, bb[3] * h], outline=color, width=3)
        label = f"{r['a']}-{r['b']} {r['relation'][:12]} gap={r['gap_px']}"
        d.text((bb[0] * w + 3, bb[3] * h - 23), label, font=load_font(17), fill=color, stroke_width=3, stroke_fill=(0, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, format="JPEG", quality=92, subsampling=0)


def draw_b_boxes(sid: str) -> Image.Image:
    source = AISLE_DIR / f"{sid}.jpg"
    im = Image.open(source).convert("RGB")
    d = ImageDraw.Draw(im)
    w, h = im.size
    raw = json.loads((B_RAW_DIR / "r1" / f"{sid}.json").read_text(encoding="utf-8"))
    for i, v in enumerate(raw.get("vehicles") or [], start=1):
        b = v.get("bbox")
        if not isinstance(b, list) or len(b) != 4:
            continue
        color = (255, 255, 255) if i % 2 else (255, 120, 120)
        d.rectangle([b[0] * w, b[1] * h, b[2] * w, b[3] * h], outline=color, width=4)
        d.text((b[0] * w + 4, b[1] * h + 3), f"B{i}", font=load_font(22), fill=color, stroke_width=3, stroke_fill=(0, 0, 0))
    d.text((8, h - 34), "B_aisle r1 original boxes (evaluation reference only)", font=load_font(20), fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    return im


def viz() -> None:
    frozen = json.loads((SESS / "frozen_inputs.json").read_text(encoding="utf-8"))
    PUB.joinpath("viz").mkdir(parents=True, exist_ok=True)
    SESS.joinpath("viz").mkdir(parents=True, exist_ok=True)
    thumbs = []
    for rec in frozen["samples"]:
        sid = rec["sample_id"]
        raw = load_raw(sid)
        if raw is None:
            continue
        asm = assemble(raw.get("parsed"), rec)
        overview = SESS / rec["overview"]["path"]
        out1 = PUB / "viz" / f"{sid}_roof_overview.jpg"
        draw_top_graph(overview, asm, out1, full_frame=False)

        full = FRAMES_DIR / f"{sid}.jpg"
        out2 = PUB / "viz" / f"{sid}_roof_full.jpg"
        draw_top_graph(full, asm, out2, full_frame=True)

        left = Image.open(out1).convert("RGB")
        right = draw_b_boxes(sid)
        scale = 900 / max(left.height, right.height)
        left = left.resize((round(left.width * scale), round(left.height * scale)), Image.Resampling.LANCZOS)
        right = right.resize((round(right.width * scale), round(right.height * scale)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (left.width + right.width + 12, max(left.height, right.height)), (20, 20, 20))
        canvas.paste(left, (0, 0))
        canvas.paste(right, (left.width + 12, 0))
        canvas.save(PUB / "viz" / f"{sid}_roof_vs_B.jpg", format="JPEG", quality=92, subsampling=0)
        thumbs.append(Image.open(out1).convert("RGB"))

    if thumbs:
        tw = 500
        resized = []
        for t in thumbs:
            th = round(t.height * tw / t.width)
            resized.append(t.resize((tw, th), Image.Resampling.LANCZOS))
        hmax = max(t.height for t in resized)
        sheet = Image.new("RGB", (tw * 2 + 12, hmax * 2 + 12), (20, 20, 20))
        for i, t in enumerate(resized):
            sheet.paste(t, ((i % 2) * (tw + 12), (i // 2) * (hmax + 12)))
        sheet.save(PUB / "viz" / "contact_sheet.jpg", format="JPEG", quality=92, subsampling=0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "run", "evaluate", "viz", "all"])
    args = ap.parse_args()
    if args.stage in {"prepare", "all"}:
        prepare_inputs()
    if args.stage in {"run", "all"}:
        run()
    if args.stage in {"evaluate", "all"}:
        evaluate()
    if args.stage in {"viz", "all"}:
        viz()


if __name__ == "__main__":
    main()
