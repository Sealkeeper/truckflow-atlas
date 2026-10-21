"""Architecture D: propose -> annotate -> adversarial audit -> verify.

Pass 1 counts and boxes trucks on the full frame.
Pass 2 receives the same frame with numbered candidate boxes rendered into it and
is asked only to find unboxed trucks, duplicates and type errors.
Every missing candidate is then independently verified from a zoom crop before
it can enter the count. This architecture is deliberately flat: no spatial
decomposition, no recursive regions.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from common import (
    EVIDENCE,
    RUNS,
    annotation_image,
    bbox_array,
    bbox_center,
    call_model,
    canonical_counts,
    frame_path,
    load_gold,
    save_crop,
    score,
    sum_calls,
    write_json,
)
from fusion import review_types
from prompts import (
    audit_prompt,
    global_count_prompt,
    verify_candidate_prompt,
)


def _candidate_text(candidates: list[dict[str, Any]]) -> str:
    lines = []
    for index, candidate in enumerate(candidates, start=1):
        box = [round(v, 3) for v in candidate["bbox_global"]]
        lines.append(
            f"{index}. size={candidate.get('size','unknown')} bbox={box} "
            f"cargo={candidate.get('cargo_color')} visible={candidate.get('visible')} "
            f"clue={candidate.get('identity_clues')}"
        )
    return "\n".join(lines) if lines else "(无候选)"


def run_case(
    camera: str,
    time_s: int,
    *,
    model: str = "doubao",
    force: bool = False,
    type_review: bool = True,
) -> dict[str, Any]:
    out_path = RUNS / "critic" / f"{camera}_{time_s}.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    frame = frame_path(camera, time_s)
    gold = load_gold()[(camera, time_s)]
    run_dir = EVIDENCE / "critic" / f"{camera}_{time_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    started = time.perf_counter()

    first = call_model(
        global_count_prompt(),
        [frame],
        model=model,
        stage="first_pass",
        max_tokens=2600,
    )
    calls.append(first)
    first_parsed = first.get("parsed") or {}
    candidates: list[dict[str, Any]] = []
    for raw in first_parsed.get("vehicles") or []:
        if raw.get("is_truck") is False:
            continue
        box = bbox_array(raw.get("bbox"))
        if box is None:
            continue
        candidates.append(
            {
                "bbox_global": box,
                "center_global": bbox_center(box),
                "size": raw.get("size", "unknown"),
                "visible": raw.get("visible", "unknown"),
                "cargo_color": raw.get("cargo_color"),
                "identity_clues": raw.get("identity_clues"),
                "evidence": raw.get("evidence"),
                "uncertain": bool(raw.get("uncertain")),
                "source": "first_pass",
            }
        )
    counts_first = canonical_counts(candidates)

    annotated_path = run_dir / "annotated_first_pass.jpg"
    annotation = annotation_image(frame, candidates, annotated_path)
    audit = call_model(
        audit_prompt(_candidate_text(candidates)),
        [frame, annotated_path],
        model=model,
        stage="audit",
        max_tokens=2200,
    )
    calls.append(audit)
    audit_parsed = audit.get("parsed") or {}

    missing_verified: list[dict[str, Any]] = []
    missing_rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(audit_parsed.get("missing") or [], start=1):
        box = bbox_array(raw.get("bbox"))
        if box is None:
            continue
        crop_path = run_dir / f"missing_{index:02d}.jpg"
        crop_meta = save_crop(
            frame, box, crop_path, pad=0.03, long_side=900, grid=False
        )
        verify = call_model(
            verify_candidate_prompt(),
            [crop_path],
            model=model,
            stage=f"verify_missing:{index}",
            max_tokens=600,
        )
        calls.append(verify)
        parsed = verify.get("parsed") or {}
        confidence = float(parsed.get("confidence") or 0.0)
        accepted = (
            verify.get("ok")
            and parsed.get("is_truck") is True
            and confidence >= 0.5
            and parsed.get("size") in ("large", "medium", "small", "unknown")
        )
        record = {
            "bbox_global": box,
            "center_global": bbox_center(box),
            "size": parsed.get("size", raw.get("size", "unknown")),
            "visible": parsed.get("visible", raw.get("visible", "unknown")),
            "cargo_color": parsed.get("cargo_color", raw.get("cargo_color")),
            "identity_clues": raw.get("identity_clues"),
            "evidence": raw.get("evidence"),
            "uncertain": bool(parsed.get("needs_review")),
            "source": "audit_missing",
            "audit_crop": crop_meta,
            "verification": {
                "accepted": accepted,
                "confidence": confidence,
                "is_truck": parsed.get("is_truck"),
                "reason": parsed.get("reason"),
            },
        }
        if accepted:
            missing_verified.append(record)
        else:
            missing_rejected.append(record)

    # Apply audit duplicates by merging the later box into the earlier one.
    drop: set[int] = set()
    duplicate_records: list[dict[str, Any]] = []
    for raw in audit_parsed.get("duplicates") or []:
        try:
            a = int(raw.get("a")) - 1
            b = int(raw.get("b")) - 1
        except (TypeError, ValueError):
            continue
        if a < 0 or b < 0 or a >= len(candidates) or b >= len(candidates) or a == b:
            continue
        keep, remove = (a, b)
        candidates[keep]["bbox_global"] = [
            min(candidates[keep]["bbox_global"][0], candidates[remove]["bbox_global"][0]),
            min(candidates[keep]["bbox_global"][1], candidates[remove]["bbox_global"][1]),
            max(candidates[keep]["bbox_global"][2], candidates[remove]["bbox_global"][2]),
            max(candidates[keep]["bbox_global"][3], candidates[remove]["bbox_global"][3]),
        ]
        candidates[keep]["center_global"] = bbox_center(candidates[keep]["bbox_global"])
        candidates[keep].setdefault("merged_from", []).append(remove + 1)
        drop.add(remove)
        duplicate_records.append(
            {"a": a + 1, "b": b + 1, "reason": raw.get("reason")}
        )

    type_corrections: list[dict[str, Any]] = []
    for raw in audit_parsed.get("type_corrections") or []:
        try:
            index = int(raw.get("id")) - 1
        except (TypeError, ValueError):
            continue
        size = raw.get("size")
        if 0 <= index < len(candidates) and size in ("large", "medium", "small"):
            before = candidates[index].get("size")
            candidates[index]["size"] = size
            type_corrections.append(
                {"id": index + 1, "before": before, "after": size, "reason": raw.get("reason")}
            )

    merged_candidates = [
        candidate for index, candidate in enumerate(candidates) if index not in drop
    ] + missing_verified
    counts_after_audit = canonical_counts(merged_candidates)
    if type_review:
        final, rejected = review_types(
            frame, merged_candidates, run_dir, calls, model=model
        )
    else:
        final, rejected = merged_candidates, []
    counts = canonical_counts(final)
    metrics = score(gold, counts)
    metrics_after_audit = score(gold, counts_after_audit)

    payload = {
        "architecture": "critic",
        "camera": camera,
        "time": time_s,
        "frame": str(frame),
        "gold": gold,
        "first_pass": first_parsed,
        "first_pass_candidates": candidates,
        "counts_first_pass": counts_first,
        "annotation": annotation,
        "audit": audit_parsed,
        "missing_verified": missing_verified,
        "missing_rejected": missing_rejected,
        "duplicates": duplicate_records,
        "type_corrections": type_corrections,
        "counts_after_audit": counts_after_audit,
        "final_vehicles": final,
        "final_vehicles_rejected_by_type_review": rejected,
        "counts": counts,
        "metrics_after_audit": metrics_after_audit,
        "metrics": metrics,
        "calls": calls,
        "cost": sum_calls(calls),
        "wall_s": round(time.perf_counter() - started, 2),
    }
    write_json(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", default="north_300,north_600,south_600,north_1200,south_1200")
    parser.add_argument("--model", default="doubao")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-type-review", action="store_true")
    args = parser.parse_args()
    for item in args.frames.split(","):
        camera, time_text = item.strip().split("_")
        result = run_case(
            camera,
            int(time_text),
            model=args.model,
            force=args.force,
            type_review=not args.no_type_review,
        )
        print(
            f"critic {item}: pred={result['counts']} gold={result['gold']['total']} "
            f"exact={result['metrics']['exact']} missing_ok={len(result['missing_verified'])} "
            f"missing_rej={len(result['missing_rejected'])} calls={result['cost']['calls']} "
            f"tokens={result['cost']['total_tokens']} wall={result['wall_s']}s"
        )


if __name__ == "__main__":
    main()
