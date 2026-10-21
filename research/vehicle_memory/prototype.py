"""Replayable vehicle-passport and memory prototype.

This module does not discover vehicles with a detector. It consumes the raw
vehicle sets returned by the already archived multimodal runs, builds passport
facets, applies explicit semantic matching, and writes an auditable report.

No network calls are made by this script. The two L2 probe responses in
``evidence/l2_probe`` were produced separately under the documented hard cap.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


VM_ROOT = Path(__file__).resolve().parent
REPO_ROOT = VM_ROOT.parents[1]
EVIDENCE = VM_ROOT / "evidence"
GENERATED = VM_ROOT / "generated"
FRAMES = REPO_ROOT / "accuracy" / "crops"

AUTO_THRESHOLD = 0.82
REVIEW_THRESHOLD = 0.52

COLOR_PATTERNS = {
    "red": ("红色", "红", "red", "暗红", "深红"),
    "white": ("白色", "白", "white", "银白"),
    "silver": ("银色", "silver"),
    "blue": ("蓝色", "蓝", "blue"),
    "gray": ("灰色", "灰", "gray", "grey", "银灰"),
    "brown": ("棕色", "棕", "brown"),
    "black": ("黑色", "黑", "black"),
    "dark": ("深色", "dark"),
}

BODY_PATTERNS = {
    "cab": ("车头", "驾驶室", "cab", "前挡"),
    "cargo": ("货厢", "车厢", "集装箱", "container", "cargo box", "封闭货"),
    "trailer": ("挂车", "trailer", "无车头", "无连接车头", "独立货厢"),
    "rigid": ("完整", "刚性", "rigid", "一体"),
}

TEXTURE_PATTERNS = {
    "corrugated": ("波纹", "瓦楞", "corrugated"),
    "container": ("集装箱", "container"),
    "flat": ("平面", "平整", "flat"),
    "roof": ("顶棚", "顶部", "顶盖", "roof"),
    "side": ("侧面", "侧板", "side"),
}

TEXT_TOKEN = re.compile(r"(?<![A-Z0-9])(?:[A-Z]{2,6}\d{3,8}|\d{5,8})(?![A-Z0-9])", re.I)
CHINESE_PLATE = re.compile(r"[\u4e00-\u9fff][A-Z]\d{4,6}", re.I)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def color_set(text: str) -> set[str]:
    lowered = compact_text(text).lower()
    return {
        color
        for color, tokens in COLOR_PATTERNS.items()
        if any(token.lower() in lowered for token in tokens)
    }


def concept_set(text: str, patterns: dict[str, tuple[str, ...]]) -> set[str]:
    lowered = compact_text(text).lower()
    return {
        concept
        for concept, tokens in patterns.items()
        if any(token.lower() in lowered for token in tokens)
    }


def text_tokens(text: str) -> list[str]:
    raw = compact_text(text)
    found = [match.group(0).upper() for match in TEXT_TOKEN.finditer(raw)]
    found.extend(match.group(0).upper() for match in CHINESE_PLATE.finditer(raw))
    # Preserve order while removing exact duplicates. No OCR correction occurs.
    return list(dict.fromkeys(found))


def phrase_color_sets(text: str) -> tuple[set[str], set[str], set[str]]:
    """Return roof, cargo and cab colours when the sentence supplies them."""
    raw = compact_text(text)
    roof: set[str] = set()
    cargo: set[str] = set()
    cab: set[str] = set()
    for clause in re.split(r"[，,；;。|/]", raw):
        colors = color_set(clause)
        if not colors:
            continue
        if any(token in clause.lower() for token in ("顶", "roof")):
            roof.update(colors)
        if any(token in clause.lower() for token in ("货厢", "车厢", "集装箱", "cargo", "container")):
            cargo.update(colors)
        if any(token in clause.lower() for token in ("车头", "驾驶室", "cab")):
            cab.update(colors)
    return roof, cargo, cab


@dataclass
class Features:
    colors: set[str] = field(default_factory=set)
    roof_colors: set[str] = field(default_factory=set)
    cargo_colors: set[str] = field(default_factory=set)
    cab_colors: set[str] = field(default_factory=set)
    bodies: set[str] = field(default_factory=set)
    textures: set[str] = field(default_factory=set)
    texts: list[str] = field(default_factory=list)
    size: str = "unknown"

    @property
    def semantic_categories(self) -> int:
        return sum(
            bool(value)
            for value in (
                self.roof_colors or self.cargo_colors or self.colors,
                self.bodies,
                self.textures,
                self.texts,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "colors": sorted(self.colors),
            "roof_colors": sorted(self.roof_colors),
            "cargo_colors": sorted(self.cargo_colors),
            "cab_colors": sorted(self.cab_colors),
            "body_types": sorted(self.bodies),
            "textures": sorted(self.textures),
            "readable_text_tokens": self.texts,
            "size": self.size,
        }


def extract_features(text: str, size: str = "unknown") -> Features:
    roof, cargo, cab = phrase_color_sets(text)
    colors = color_set(text)
    return Features(
        colors=colors,
        roof_colors=roof,
        cargo_colors=cargo,
        cab_colors=cab,
        bodies=concept_set(text, BODY_PATTERNS),
        textures=concept_set(text, TEXTURE_PATTERNS),
        texts=text_tokens(text),
        size=size.lower() if size else "unknown",
    )


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def size_similarity(left: str, right: str) -> float:
    if left == "unknown" or right == "unknown":
        return 0.0
    return 1.0 if left == right else 0.0


@dataclass
class Observation:
    sample_id: str
    camera: str
    time_s: int
    index: int
    bbox: list[float]
    clues: str
    evidence: str
    visible: str
    uncertain: bool
    features: Features
    source: str
    text_verified: bool = False
    run: dict[str, Any] = field(default_factory=dict)

@dataclass
class Match:
    left: Observation
    right: Observation
    score: float
    decision: str
    matched_categories: list[str]
    conflicts: list[str]
    reason: str


def compare(one: Observation, two: Observation, *, targeted: bool = False) -> Match:
    a, b = one.features, two.features
    conflicts: list[str] = []
    matched: list[str] = []

    text_exact = bool(set(a.texts) & set(b.texts))
    text_conflict = bool(a.texts and b.texts and not set(a.texts) & set(b.texts))
    if text_exact:
        matched.append("exact_readable_text")
    if text_conflict:
        conflicts.append("readable_text_disagrees")

    cargo_color_similarity = jaccard(a.cargo_colors or a.colors, b.cargo_colors or b.colors)
    roof_color_similarity = jaccard(a.roof_colors, b.roof_colors)
    cab_color_similarity = jaccard(a.cab_colors, b.cab_colors)
    body_similarity = jaccard(a.bodies, b.bodies)
    texture_similarity = jaccard(a.textures, b.textures)
    size_similarity_value = size_similarity(a.size, b.size)

    if cargo_color_similarity > 0:
        matched.append("cargo_colour")
    if roof_color_similarity > 0:
        matched.append("roof_colour")
    if body_similarity > 0:
        matched.append("body_type")
    if texture_similarity > 0:
        matched.append("texture")

    if "cargo" in a.bodies and "cab" in b.bodies and not ("cab" in a.bodies or "cargo" in b.bodies):
        conflicts.append("body_roles_disagree")
    if "cab" in a.bodies and "cargo" in b.bodies and not ("cargo" in a.bodies or "cab" in b.bodies):
        conflicts.append("body_roles_disagree")
    if a.size != "unknown" and b.size != "unknown" and a.size != b.size:
        conflicts.append("size_disagrees")

    # Geometry is deliberately absent: a box coordinate is evidence in its
    # source frame, not a cross-camera identity feature.
    score = (
        0.32 * cargo_color_similarity
        + 0.18 * roof_color_similarity
        + 0.18 * body_similarity
        + 0.12 * texture_similarity
        + 0.10 * cab_color_similarity
        + 0.10 * size_similarity_value
    )
    if text_exact:
        score = max(score, 0.98)
    if text_conflict:
        score = min(score, 0.35)

    if text_exact and one.text_verified and two.text_verified:
        decision = "auto"
        reason = "validated exact readable identifier"
    elif text_exact:
        decision = "review"
        reason = "verbatim text agrees but has not been validated as OCR or a box number"
    elif targeted and not conflicts and len(set(matched)) >= 2 and score >= 0.52:
        decision = "auto"
        reason = "targeted-crop duplicate with at least two semantic witnesses"
    elif conflicts:
        decision = "reject" if score < REVIEW_THRESHOLD else "review"
        reason = "conflicting semantic evidence"
    elif score >= AUTO_THRESHOLD and len(set(matched)) >= 2:
        decision = "auto"
        reason = "high score with at least two semantic witnesses"
    elif score >= REVIEW_THRESHOLD or cargo_color_similarity > 0 or roof_color_similarity > 0:
        decision = "review"
        reason = "same-colour or weak semantic evidence is insufficient"
    else:
        decision = "reject"
        reason = "below review threshold with no shared identity feature"

    return Match(
        left=one,
        right=two,
        score=round(score, 4),
        decision=decision,
        matched_categories=sorted(set(matched)),
        conflicts=sorted(set(conflicts)),
        reason=reason,
    )


def parse_aisle_runs() -> list[Observation]:
    observations: list[Observation] = []
    for path in sorted((EVIDENCE / "aisle_clean").glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = read_json(path)
        run = next((item for item in payload.get("runs", []) if item.get("ok")), None)
        if not run:
            continue
        sample_id = path.stem.replace("_aisle", "")
        camera, time_text = sample_id.split("_", 1)
        for index, vehicle in enumerate(run.get("parsed", {}).get("vehicles", []), start=1):
            clues = compact_text(vehicle.get("identity_clues"))
            observations.append(
                Observation(
                    sample_id=sample_id,
                    camera=camera,
                    time_s=int(time_text),
                    index=index,
                    bbox=[float(value) for value in vehicle["bbox"]],
                    clues=clues,
                    evidence=compact_text(vehicle.get("evidence")),
                    visible=compact_text(vehicle.get("visible") or "unknown"),
                    uncertain=bool(vehicle.get("uncertain")),
                    features=extract_features(
                        " ".join(
                            part
                            for part in (
                                clues,
                                compact_text(vehicle.get("evidence")),
                                compact_text(vehicle.get("visible")),
                            )
                            if part
                        ),
                        compact_text(vehicle.get("size") or "unknown"),
                    ),
                    source=str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    run={
                        "model": run.get("model"),
                        "model_id": run.get("model_id"),
                        "latency_s": run.get("latency_s"),
                        "total_tokens": (run.get("usage") or {}).get("total_tokens"),
                    },
                )
            )
    return observations


def parse_truth() -> dict[int, dict[str, Any]]:
    payload = read_json(REPO_ROOT / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json")
    return {
        int(sample["time"]): {
            "sample_key": sample["sample_key"],
            "camera_counts": sample["camera_counts"],
            "overlap": int(sample["overlap"]),
            "unique_total": int(sample["unique_total"]),
        }
        for sample in payload["samples"]
    }


def crop_for_observation(observation: Observation) -> str:
    crop_dir = GENERATED / "passport_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    source = FRAMES / f"{observation.sample_id}_aisle.jpg"
    output = crop_dir / f"{observation.sample_id}__{observation.index:02d}.jpg"
    if source.exists():
        with Image.open(source).convert("RGB") as image:
            width, height = image.size
            x0, y0, x1, y1 = observation.bbox
            pad_x, pad_y = max(0.01, (x1 - x0) * 0.08), max(0.01, (y1 - y0) * 0.05)
            pixels = (
                max(0, round((x0 - pad_x) * width)),
                max(0, round((y0 - pad_y) * height)),
                min(width, round((x1 + pad_x) * width)),
                min(height, round((y1 + pad_y) * height)),
            )
            crop = image.crop(pixels)
            crop.thumbnail((320, 320), Image.Resampling.LANCZOS)
            crop.save(output, quality=88, optimize=True)
    return str(output.relative_to(REPO_ROOT)).replace("\\", "/")


def build_identity_layers(observation: Observation, passport_id: str) -> dict[str, Any]:
    session_id = "vs_" + hashlib.sha1(
        f"{passport_id}:{observation.sample_id}:{observation.index}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "cargo_id": {
            "value": None,
            "status": "unobserved_or_unverified",
            "scope": "cargo_only",
            "candidate_tokens": [],
            "note": (
                "No raw text is promoted into this typed layer. Unclassified model text "
                "cannot establish that a token is a container number."
            ),
        },
        "tractor_id": {
            "value": None,
            "status": "unobserved_or_unverified",
            "scope": "tractor_only",
            "candidate_tokens": [],
            "note": (
                "No raw text is promoted into this typed layer. Unclassified model text "
                "cannot establish that a token is a tractor plate."
            ),
        },
        "vehicle_session_id": {
            "value": session_id,
            "status": "provisional",
            "scope": "single_observation_only",
            "derived_from": ["current_frame_observation"],
            "note": "No cross-frame or cross-camera session continuity has been asserted.",
        },
    }


def build_memory_metadata(
    observation: Observation, created_at: datetime
) -> dict[str, Any]:
    ttl_s = 300
    expires_at = created_at + timedelta(seconds=ttl_s)
    return {
        "source": observation.source,
        "observed_at_video_s": observation.time_s,
        "created_at_utc": created_at.isoformat(),
        "version": "passport-v1",
        "ttl_s": ttl_s,
        "expires_at_utc": expires_at.isoformat(),
        "state": "fresh",
        "conflicts": [],
        "supersedes": [],
    }


def build_passport(observation: Observation, created_at: datetime) -> dict[str, Any]:
    raw_id = f"{observation.sample_id}:{observation.camera}:{observation.index}"
    passport_id = "vp_" + hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]
    confidence = 0.45
    confidence += 0.08 if observation.features.texts else 0.0
    confidence += 0.06 if observation.features.colors else 0.0
    confidence += 0.06 if observation.features.bodies else 0.0
    confidence += 0.06 if observation.features.textures else 0.0
    confidence -= 0.20 if observation.uncertain else 0.0
    return {
        "passport_id": passport_id,
        "first_seen": {
            "video_time_s": observation.time_s,
            "frame_key": observation.sample_id,
        },
        "last_seen": {
            "video_time_s": observation.time_s,
            "frame_key": observation.sample_id,
        },
        "cameras": [observation.camera],
        "bbox_history": [
            {
                "frame_key": observation.sample_id,
                "camera": observation.camera,
                "bbox_normalized": observation.bbox,
                "visible": observation.visible,
            }
        ],
        "visual": {
            "roof_color": sorted(observation.features.roof_colors),
            "roof_texture": sorted(observation.features.textures),
            "cargo_color": sorted(observation.features.cargo_colors or observation.features.colors),
            "cargo_type": sorted(observation.features.bodies),
            "cab_color": sorted(observation.features.cab_colors),
        },
        "readable_text": {
            "verbatim": observation.clues,
            "tokens": observation.features.texts,
            "verified": observation.text_verified,
            "policy": (
                "verbatim only; missing or uncertain text is never reconstructed, and "
                "unclassified tokens are not promoted to cargo_id or tractor_id"
            ),
        },
        "identity_layers": build_identity_layers(observation, passport_id),
        "memory_metadata": build_memory_metadata(observation, created_at),
        "dimension_class": observation.features.size,
        "evidence_crops": [crop_for_observation(observation)],
        "confidence": round(max(0.0, min(0.95, confidence)), 3),
        "status": "provisional",
        "provenance": {
            "source": observation.source,
            "model": observation.run.get("model"),
            "model_id": observation.run.get("model_id"),
            "raw_identity_clues": observation.clues,
            "raw_evidence": observation.evidence,
            "uncertain_flag": observation.uncertain,
            "paid_calls": 1,
            "total_tokens": observation.run.get("total_tokens"),
            "latency_s": observation.run.get("latency_s"),
        },
        "merge_history": [],
        "notes": [
            "Observation-level provisional passport facet. No cross-camera identity is asserted.",
        ],
    }


def build_memory_cache(
    passports: list[dict[str, Any]],
    l2: dict[str, Any],
    per_camera_rows: list[dict[str, Any]],
    created_at: datetime,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for passport in passports:
        metadata = passport["memory_metadata"]
        entries.append(
            {
                "memory_id": "mem_l1_" + passport["passport_id"].removeprefix("vp_"),
                "layer": "L1",
                "memory_type": "provisional_passport_facet",
                "key": passport["passport_id"],
                "summary": "Observation-level semantic identity evidence; not a permanent vehicle ID.",
                "payload_ref": "generated/passports.json#" + passport["passport_id"],
                **metadata,
            }
        )

    l2_created = created_at.isoformat()
    l2_expires = (created_at + timedelta(days=30)).isoformat()
    for row in l2["frames"]:
        entries.append(
            {
                "memory_id": "mem_l2_" + row["sample_id"],
                "layer": "L2",
                "memory_type": "scene_miss_region_probe",
                "key": row["sample_id"],
                "summary": (
                    f"main={row['main_count']}, supplement={row['supplement_raw_count']}, "
                    f"new={row['supplement_new_count']}, merged={row['merged_count']}, "
                    f"gold={row['gold_camera_count']}"
                ),
                "payload_ref": "evidence/l2_probe/" + row["sample_id"],
                "source": "research/vehicle_memory/evidence/l2_probe",
                "observed_at_video_s": int(row["sample_id"].split("_", 1)[1]),
                "created_at_utc": l2_created,
                "version": "l2-probe-v1",
                "ttl_s": 30 * 24 * 60 * 60,
                "expires_at_utc": l2_expires,
                "state": "fresh",
                "conflicts": [],
                "supersedes": [],
            }
        )

    l3_created = created_at.isoformat()
    l3_expires = (created_at + timedelta(days=90)).isoformat()
    for row in per_camera_rows:
        if row["exact"]:
            continue
        entries.append(
            {
                "memory_id": "mem_l3_" + row["sample_id"],
                "layer": "L3",
                "memory_type": "count_failure_regression",
                "key": row["sample_id"],
                "summary": (
                    f"baseline predicted {row['predicted']}, gold {row['gold']}, "
                    f"error {row['error']:+d}"
                ),
                "payload_ref": "generated/metrics.json#per_camera_baseline",
                "source": "research/vehicle_memory/evidence/aisle_clean",
                "observed_at_video_s": row["time_s"],
                "created_at_utc": l3_created,
                "version": "clean-baseline-pr9",
                "ttl_s": 90 * 24 * 60 * 60,
                "expires_at_utc": l3_expires,
                "state": "fresh",
                "conflicts": [],
                "supersedes": [],
            }
        )

    return {
        "schema": "truckflow-memory-cache-v1",
        "created_at_utc": created_at.isoformat(),
        "identity_policy": {
            "container_number_is_vehicle_id": False,
            "cargo_id_scope": "cargo_only",
            "tractor_id_scope": "tractor_only",
            "vehicle_session_requires_current_attachment_or_continuity_evidence": True,
            "unclear_ocr_may_merge": False,
            "trailer_swap_creates_new_session": True,
        },
        "entries": entries,
    }


def predict_cross_camera(
    observations: list[Observation],
) -> list[dict[str, Any]]:
    by_time: dict[int, list[Observation]] = {}
    for observation in observations:
        by_time.setdefault(observation.time_s, []).append(observation)

    rows: list[dict[str, Any]] = []
    for time_s in sorted(by_time):
        group = by_time[time_s]
        north = [item for item in group if item.camera == "north"]
        south = [item for item in group if item.camera == "south"]
        candidates = [compare(one, two) for one in north for two in south]
        candidates.sort(key=lambda item: item.score, reverse=True)
        used_left: set[int] = set()
        used_right: set[int] = set()
        selected: list[Match] = []
        for candidate in candidates:
            if candidate.decision == "reject":
                continue
            if id(candidate.left) in used_left or id(candidate.right) in used_right:
                continue
            used_left.add(id(candidate.left))
            used_right.add(id(candidate.right))
            selected.append(candidate)

        auto = [item for item in selected if item.decision == "auto"]
        review = [item for item in selected if item.decision == "review"]
        both_views_occupied = bool(north and south)
        release_status = (
            "review"
            if review or (both_views_occupied and not auto)
            else "auto"
        )
        if review:
            release_reason = "unresolved cross-camera candidate remains"
        elif both_views_occupied and not auto:
            release_reason = "two occupied views without a verified cross-camera pair"
        else:
            release_reason = "no unresolved two-view occupancy"
        rows.append(
            {
                "time_s": time_s,
                "north_count": len(north),
                "south_count": len(south),
                "naive_sum": len(north) + len(south),
                "auto_matches": [
                    {
                        "north": item.left.index,
                        "south": item.right.index,
                        "score": item.score,
                        "matched_categories": item.matched_categories,
                        "reason": item.reason,
                    }
                    for item in auto
                ],
                "review_matches": [
                    {
                        "north": item.left.index,
                        "south": item.right.index,
                        "score": item.score,
                        "matched_categories": item.matched_categories,
                        "conflicts": item.conflicts,
                        "reason": item.reason,
                    }
                    for item in review
                ],
                "best_candidate_scores": [
                    {
                        "north": item.left.index,
                        "south": item.right.index,
                        "score": item.score,
                        "decision": item.decision,
                        "matched_categories": item.matched_categories,
                        "conflicts": item.conflicts,
                    }
                    for item in candidates[:5]
                ],
                "raw_auto_unique": len(north) + len(south) - len(auto),
                "review_gated": release_status == "review",
                "release_reason": release_reason,
                "release_status": release_status,
            }
        )
    return rows


def pair_probe_metrics() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    tp = fp = fn = tn = review = 0
    for path in sorted((EVIDENCE / "pair_probes").glob("*.json")):
        payload = read_json(path)
        run = payload.get("run", {})
        parsed = run.get("parsed", {}) or {}
        gold = payload.get("gold_answer")
        answer = compact_text(parsed.get("answer")).lower() or "uncertain"
        is_review = bool(parsed.get("review")) or answer == "uncertain" or not run.get("ok")
        review += int(is_review)
        if answer == "yes" and gold == "yes":
            tp += 1
        elif answer == "yes" and gold == "no":
            fp += 1
        elif answer != "yes" and gold == "yes":
            fn += 1
        elif answer == "no" and gold == "no":
            tn += 1
        rows.append(
            {
                "case": payload.get("case"),
                "model": run.get("model"),
                "gold": gold,
                "answer": answer,
                "exact": answer == gold,
                "review": is_review,
                "latency_s": run.get("latency_s"),
                "total_tokens": (run.get("usage") or {}).get("total_tokens"),
            }
        )
    metrics = {
        "decisions": len(rows),
        "exact": sum(row["exact"] for row in rows),
        "exact_rate": round(sum(row["exact"] for row in rows) / max(1, len(rows)), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision_committed_yes": round(tp / max(1, tp + fp), 4),
        "recall_committed_yes": round(tp / max(1, tp + fn), 4),
        "review_count": review,
        "review_rate": round(review / max(1, len(rows)), 4),
        "latency_s_sum": round(sum(float(row.get("latency_s") or 0) for row in rows), 3),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in rows),
    }
    return metrics, rows


PAIR_CASES = [
    ("t600_red_positive", "north_600", "N6", "south_600", "S6", "yes"),
    ("t600_white_positive", "north_600", "N8", "south_600", "S7", "yes"),
    ("t600_blue_vs_far_red", "north_600", "N4", "south_600", "S3", "no"),
    ("t600_blue_vs_red_cab", "north_600", "N5", "south_600", "S5", "no"),
    ("t1200_red_positive", "north_1200", "N7", "south_1200", "S6", "yes"),
    ("t1200_white_positive", "north_1200", "N8", "south_1200", "S7", "yes"),
    ("t1200_blue_vs_far_red", "north_1200", "N4", "south_1200", "S2", "no"),
    ("t1200_red_vs_red_cab", "north_1200", "N7", "south_1200", "S5", "no"),
]


def candidate_observations() -> dict[tuple[str, str], list[Observation]]:
    candidates = read_json(REPO_ROOT / "data" / "candidates.json")
    result: dict[tuple[str, str], list[Observation]] = {}
    for sample_id, items in candidates.items():
        camera, time_text = sample_id.split("_", 1)
        for item in items:
            observations: list[Observation] = []
            for index, proposal in enumerate(item.get("proposals", []), start=1):
                clues = compact_text(proposal.get("identity_clues"))
                observations.append(
                    Observation(
                        sample_id=sample_id,
                        camera=camera,
                        time_s=int(time_text),
                        index=index,
                        bbox=[float(value) for value in proposal.get("bbox", item.get("bbox", [0, 0, 0, 0]))],
                        clues=clues,
                        evidence=clues,
                        visible=compact_text(proposal.get("visible") or "unknown"),
                        uncertain=bool(proposal.get("uncertain")),
                        features=extract_features(clues, compact_text(proposal.get("model_size") or "unknown")),
                        source="data/candidates.json",
                        run={"model": proposal.get("model"), "source_mode": proposal.get("source_mode")},
                    )
                )
            result[(sample_id, item["candidate"])] = observations
    return result


def memory_pair_case_metrics() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = candidate_observations()
    rows: list[dict[str, Any]] = []
    tp = fp = fn = tn = review = 0
    for case, north_id, north_candidate, south_id, south_candidate, gold in PAIR_CASES:
        north = candidates[(north_id, north_candidate)]
        south = candidates[(south_id, south_candidate)]
        matches = [compare(one, two) for one in north for two in south]
        best = max(matches, key=lambda item: item.score)
        answer = "yes" if best.decision == "auto" else "no" if best.decision == "reject" else "uncertain"
        is_review = best.decision == "review"
        review += int(is_review)
        if answer == "yes" and gold == "yes":
            tp += 1
        elif answer == "yes" and gold == "no":
            fp += 1
        elif answer != "yes" and gold == "yes":
            fn += 1
        elif answer == "no" and gold == "no":
            tn += 1
        rows.append(
            {
                "case": case,
                "gold": gold,
                "answer": answer,
                "score": best.score,
                "decision": best.decision,
                "matched_categories": best.matched_categories,
                "conflicts": best.conflicts,
                "exact": answer == gold,
                "review": is_review,
            }
        )
    metrics = {
        "cases": len(rows),
        "exact": sum(row["exact"] for row in rows),
        "exact_rate": round(sum(row["exact"] for row in rows) / max(1, len(rows)), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision_committed_yes": round(tp / max(1, tp + fp), 4),
        "recall_committed_yes": round(tp / max(1, tp + fn), 4),
        "review_count": review,
        "review_rate": round(review / max(1, len(rows)), 4),
    }
    return metrics, rows


def probe_vehicles(path: Path) -> list[Observation]:
    payload = read_json(path)
    run = next(item for item in payload["runs"] if item.get("ok"))
    name = path.stem.replace("_doubao", "")
    name = re.sub(r"_(?:farzoom|farpair)$", "", name)
    camera, time_text = name.split("_", 1)
    result: list[Observation] = []
    for index, vehicle in enumerate(run["parsed"].get("vehicles", []), start=1):
        clue = " ".join(
            compact_text(vehicle.get(key))
            for key in ("roof_color", "roof_texture", "cargo_color", "cargo_type", "cab_color", "readable_text", "evidence")
            if vehicle.get(key)
        )
        result.append(
            Observation(
                sample_id=name,
                camera=camera,
                time_s=int(time_text),
                index=index,
                bbox=[float(value) for value in vehicle["bbox"]],
                clues=clue,
                evidence=compact_text(vehicle.get("evidence")),
                visible=compact_text(vehicle.get("vehicle_type") or "unknown"),
                uncertain=bool(vehicle.get("uncertain")),
                features=extract_features(clue, compact_text(vehicle.get("size") or "unknown")),
                source=str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                run=run,
            )
        )
    return result


def map_crop_to_aisle(bbox: list[float], meta: dict[str, Any]) -> list[float]:
    crop = meta["crop_normalized"]
    x0 = crop[0] + bbox[0] * (crop[2] - crop[0])
    y0 = crop[1] + bbox[1] * (crop[3] - crop[1])
    x1 = crop[0] + bbox[2] * (crop[2] - crop[0])
    y1 = crop[1] + bbox[3] * (crop[3] - crop[1])
    # The archived main view is a 350..870 pixel crop of the 1280 px frame.
    aisle_x0, aisle_x1 = 350 / 1280, 870 / 1280
    return [
        (x0 - aisle_x0) / (aisle_x1 - aisle_x0),
        y0,
        (x1 - aisle_x0) / (aisle_x1 - aisle_x0),
        y1,
    ]


def l2_point_experiment(
    observations: list[Observation], truth: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    main_by_sample = {
        sample: [item for item in observations if item.sample_id == sample]
        for sample in ("north_5", "north_600")
    }
    results: list[dict[str, Any]] = []
    for sample in ("north_5", "north_600"):
        probe_path = EVIDENCE / "l2_probe" / f"{sample}_"
        if sample == "north_5":
            probe_path = EVIDENCE / "l2_probe" / "north_5_farzoom_doubao.json"
            meta_path = EVIDENCE / "l2_probe" / "north_5_farzoom.meta.json"
        else:
            probe_path = EVIDENCE / "l2_probe" / "north_600_farpair_doubao.json"
            meta_path = EVIDENCE / "l2_probe" / "north_600_farpair.meta.json"
        supplement = probe_vehicles(probe_path)
        meta = read_json(meta_path)
        for item in supplement:
            item.bbox = map_crop_to_aisle(item.bbox, meta)
        main = main_by_sample[sample]
        duplicate_pairs: list[Match] = []
        additions: list[Observation] = []
        for candidate in supplement:
            matches = sorted(
                (compare(candidate, existing, targeted=True) for existing in main),
                key=lambda item: item.score,
                reverse=True,
            )
            best = matches[0] if matches else None
            if best and best.decision == "auto":
                duplicate_pairs.append(best)
            else:
                additions.append(candidate)
        before = len(main)
        after = len(main) + len(additions)
        gold = truth[int(sample.split("_", 1)[1])]["camera_counts"]["north"]
        results.append(
            {
                "sample_id": sample,
                "gold_camera_count": gold,
                "main_count": before,
                "supplement_raw_count": len(supplement),
                "supplement_new_count": len(additions),
                "merged_count": after,
                "absolute_error_before": abs(before - gold),
                "absolute_error_after": abs(after - gold),
                "duplicate_matches": [
                    {
                        "supplement_index": item.left.index,
                        "main_index": item.right.index,
                        "score": item.score,
                        "matched_categories": item.matched_categories,
                    }
                    for item in duplicate_pairs
                ],
                "new_vehicle_evidence": [
                    {
                        "supplement_index": item.index,
                        "clues": item.clues,
                        "bbox_in_aisle_view": [round(value, 4) for value in item.bbox],
                    }
                    for item in additions
                ],
                "probe_total_tokens": (supplement[0].run.get("usage") or {}).get("total_tokens") if supplement else 0,
                "probe_latency_s": supplement[0].run.get("latency_s") if supplement else None,
            }
        )
    before_mae = statistics.mean(row["absolute_error_before"] for row in results)
    after_mae = statistics.mean(row["absolute_error_after"] for row in results)
    return {
        "scope": "two historical easy-miss frames only; not a 20-frame accuracy claim",
        "frames": results,
        "camera_count_mae_before": round(before_mae, 4),
        "camera_count_mae_after": round(after_mae, 4),
        "corrected_frames": sum(row["absolute_error_after"] < row["absolute_error_before"] for row in results),
        "regressed_frames": sum(row["absolute_error_after"] > row["absolute_error_before"] for row in results),
        "new_calls": len(results),
        "total_tokens": sum(int(row["probe_total_tokens"] or 0) for row in results),
        "latency_s_sum": round(sum(float(row["probe_latency_s"] or 0) for row in results), 3),
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def main() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    observations = parse_aisle_runs()
    truth = parse_truth()
    passports = [build_passport(observation, created_at) for observation in observations]

    by_sample = Counter(item.sample_id for item in observations)
    per_camera_rows: list[dict[str, Any]] = []
    for time_s, gold in sorted(truth.items()):
        for camera in ("north", "south"):
            sample_id = f"{camera}_{time_s}"
            predicted = by_sample[sample_id]
            expected = int(gold["camera_counts"][camera])
            per_camera_rows.append(
                {
                    "sample_id": sample_id,
                    "camera": camera,
                    "time_s": time_s,
                    "gold": expected,
                    "predicted": predicted,
                    "error": predicted - expected,
                    "exact": predicted == expected,
                }
            )

    per_camera_mae = statistics.mean(abs(row["error"]) for row in per_camera_rows)
    per_camera_exact = sum(row["exact"] for row in per_camera_rows)

    cross_camera = predict_cross_camera(observations)
    unique_naive: list[dict[str, Any]] = []
    for row in cross_camera:
        gold = truth[row["time_s"]]
        unique_naive.append(
            {
                **row,
                "gold_unique": gold["unique_total"],
                "gold_overlap": gold["overlap"],
                "naive_error": row["naive_sum"] - gold["unique_total"],
                "raw_auto_unique_error": row["raw_auto_unique"] - gold["unique_total"],
            }
        )

    naive_unique_mae = statistics.mean(abs(row["naive_error"]) for row in unique_naive)
    raw_auto_unique_mae = statistics.mean(abs(row["raw_auto_unique_error"]) for row in unique_naive)
    auto_released_frames = [row for row in unique_naive if row["release_status"] == "auto"]
    auto_errors = [
        row for row in auto_released_frames if row["raw_auto_unique"] != row["gold_unique"]
    ]
    review_frames = [row for row in unique_naive if row["release_status"] == "review"]
    auto_duplicate_count = sum(len(row["auto_matches"]) for row in unique_naive)
    review_duplicate_count = sum(len(row["review_matches"]) for row in unique_naive)
    gold_duplicate_count = sum(row["gold_overlap"] for row in unique_naive)
    visible_count = sum(row["naive_sum"] for row in unique_naive)

    probe_metrics, probe_rows = pair_probe_metrics()
    memory_pair_metrics, memory_pair_rows = memory_pair_case_metrics()
    l2 = l2_point_experiment(observations, truth)

    # The run-level fields are repeated on every observation; sum once per sample.
    seen_samples: set[str] = set()
    main_tokens = 0
    main_latency = 0.0
    calls_per_sample = Counter()
    for observation in observations:
        if observation.sample_id in seen_samples:
            continue
        seen_samples.add(observation.sample_id)
        main_tokens += int(observation.run.get("total_tokens") or 0)
        main_latency += float(observation.run.get("latency_s") or 0)
        calls_per_sample[observation.sample_id] = 1

    supplement_samples = {
        row["sample_id"] for row in l2["frames"] if int(row["probe_total_tokens"] or 0) > 0
    }
    for sample in supplement_samples:
        calls_per_sample[sample] += 1

    total_calls = sum(calls_per_sample.values())
    total_tokens = main_tokens + int(l2["total_tokens"])
    total_latency = main_latency + float(l2["latency_s_sum"])
    call_values = list(calls_per_sample.values())
    evaluated_camera_frames = len(per_camera_rows)
    cost = {
        "unit": "camera-frame",
        "camera_frames": evaluated_camera_frames,
        "time_groups": len(truth),
        "main_calls": evaluated_camera_frames,
        "supplement_calls": len(supplement_samples),
        "total_calls": total_calls,
        "mean_calls_per_camera_frame": round(
            total_calls / max(1, evaluated_camera_frames), 4
        ),
        "mean_calls_per_time_group": round(total_calls / max(1, len(truth)), 4),
        "p50_calls_per_camera_frame": round(percentile(call_values, 0.5), 4),
        "p95_calls_per_camera_frame": round(percentile(call_values, 0.95), 4),
        "max_calls_per_camera_frame": max(call_values, default=0),
        "share_camera_frames_with_supplement_call": round(
            len(supplement_samples) / max(1, evaluated_camera_frames), 4
        ),
        "main_latency_s_sum": round(main_latency, 3),
        "l2_latency_s_sum": round(float(l2["latency_s_sum"]), 3),
        "total_latency_s_sum": round(total_latency, 3),
        "mean_camera_frame_latency_s": round(
            total_latency / max(1, evaluated_camera_frames), 3
        ),
        "total_tokens": total_tokens,
        "main_tokens": main_tokens,
        "l2_tokens": int(l2["total_tokens"]),
        "new_calls_in_this_session": int(l2["new_calls"]),
        "replayed_archived_main_calls": evaluated_camera_frames,
        "archived_pair_probe_calls_not_used_online": len(probe_rows),
        "pair_probe_tokens_for_audit_only": probe_metrics["total_tokens"],
    }

    memory_candidate_pairs = sum(
        len([item for item in observations if item.camera == "north" and item.time_s == time_s])
        * len([item for item in observations if item.camera == "south" and item.time_s == time_s])
        for time_s in truth
    )

    # The L2 experiment changes only two historical easy-miss camera counts.
    l2_adjusted_rows = []
    l2_by_sample = {row["sample_id"]: row["merged_count"] for row in l2["frames"]}
    for row in per_camera_rows:
        predicted = l2_by_sample.get(row["sample_id"], row["predicted"])
        l2_adjusted_rows.append(
            {
                **row,
                "predicted": predicted,
                "error": predicted - row["gold"],
                "exact": predicted == row["gold"],
            }
        )
    memory_cache = build_memory_cache(passports, l2, per_camera_rows, created_at)

    result = {
        "schema": "truckflow-vehicle-memory-replay-v2",
        "generated_at": created_at.isoformat(),
        "constraints": {
            "identity_decision": (
                "semantic passport matching only; no detector, tracker, or cross-camera "
                "box geometry identity"
            ),
            "auto_threshold": AUTO_THRESHOLD,
            "review_threshold": REVIEW_THRESHOLD,
            "silent_merge": False,
            "new_model_calls": l2["new_calls"],
            "identity_policy": memory_cache["identity_policy"],
        },
        "dataset": {
            "samples": len(per_camera_rows),
            "times": len(truth),
            "observations": len(observations),
            "provisional_passport_facets": len(passports),
        },
        "per_camera_baseline": {
            "exact": per_camera_exact,
            "n": len(per_camera_rows),
            "exact_rate": round(per_camera_exact / len(per_camera_rows), 4),
            "mae": round(per_camera_mae, 4),
            "rows": per_camera_rows,
        },
        "l2_adjusted_per_camera": {
            "exact": sum(row["predicted"] == row["gold"] for row in l2_adjusted_rows),
            "n": len(l2_adjusted_rows),
            "mae": round(statistics.mean(abs(row["error"]) for row in l2_adjusted_rows), 4),
            "rows": l2_adjusted_rows,
        },
        "cross_camera": {
            "naive_unique_mae": round(naive_unique_mae, 4),
            "raw_auto_unique_mae": round(raw_auto_unique_mae, 4),
            "gold_overlap_count": gold_duplicate_count,
            "visible_detection_count": visible_count,
            "gold_overlap_rate_of_visible": round(gold_duplicate_count / visible_count, 4),
            "auto_duplicate_count": auto_duplicate_count,
            "review_duplicate_count": review_duplicate_count,
            "auto_released_frames": len(auto_released_frames),
            "auto_released_frame_errors": len(auto_errors),
            "review_frames": len(review_frames),
            "review_rate": round(len(review_frames) / len(unique_naive), 4),
            "rows": unique_naive,
        },
        "pair_probe_archived_models": probe_metrics,
        "pair_probe_archived_rows": probe_rows,
        "memory_pair_cases": memory_pair_metrics,
        "memory_pair_case_rows": memory_pair_rows,
        "l2_point_experiment": l2,
        "cost": cost,
        "call_savings": {
            "candidate_cross_camera_pairs_enumerated": memory_candidate_pairs,
            "model_pair_verification_calls_used": 0,
            "verified_automatic_hits": 0,
            "saved_model_calls": 0,
            "archived_pair_probe_calls_not_replayed": len(probe_rows),
            "rule": (
                "A confirmed passport hard-ID hit replaces one model pair-verification call. "
                "The main occupancy call is never skipped because a known vehicle may have left."
            ),
        },
    }

    write_json(
        GENERATED / "passports.json",
        {
            "schema": "truckflow-passports-v1",
            "identity_method": "semantic_passport_only",
            "traditional_detection_or_tracking_used": False,
            "identity_policy": memory_cache["identity_policy"],
            "passports": passports,
        },
    )
    write_json(GENERATED / "memory_cache.json", memory_cache)
    write_json(GENERATED / "metrics.json", result)
    write_json(GENERATED / "pair_probes.json", {"metrics": probe_metrics, "rows": probe_rows})
    write_json(
        GENERATED / "memory_pair_cases.json",
        {"metrics": memory_pair_metrics, "rows": memory_pair_rows},
    )

    print(json.dumps(result["per_camera_baseline"], ensure_ascii=False, indent=2))
    print(json.dumps(result["cross_camera"], ensure_ascii=False, indent=2, default=str)[:12000])
    print(json.dumps(result["pair_probe_archived_models"], ensure_ascii=False, indent=2))
    print(json.dumps(result["memory_pair_cases"], ensure_ascii=False, indent=2))
    print(json.dumps(result["l2_point_experiment"], ensure_ascii=False, indent=2))
    print(json.dumps(result["cost"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
