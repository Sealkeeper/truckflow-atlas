"""Offline, fail-closed annotation gate and Qwen-style JSONL exporter.

No network, model loading, training, directory scanning, or label generation.
This checks supplied provenance; it cannot certify that a human label is true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

SPLITS = {"train", "dev", "blind", "regression"}
PROMPT = (
    "<image>\n识别当前图像实际可见且可确认的货车，逐辆列出，不把牵引车和其挂车拆开。"
    "完全遮挡不计；不确定车型写unknown。输出JSON：total、vehicles；"
    "每辆含local_id、bbox_2d、type、visibility、evidence。"
    "bbox_2d为相对本图宽高归一化到0至1000的[x1,y1,x2,y2]整数。"
    "只按当前图像证据判断，不根据历史数量或容量补车。"
)


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(rows, guard_s=60):
    """Return all actionable defects; no mutable source data or inferred labels."""
    errors = []
    seen_ids = set()
    group_splits = defaultdict(set)
    valid_intervals = []
    for row in rows:
        sid = row.get("sample_id", "<missing>")
        prefix = f"{sid}:"
        if sid in seen_ids or sid == "<missing>":
            errors.append(prefix + "duplicate_or_missing_sample_id")
        seen_ids.add(sid)
        split = row.get("split")
        if split not in SPLITS:
            errors.append(prefix + "invalid_split")
        for field in ("capture_session_id", "time_block", "near_duplicate_group", "sha256", "image", "camera", "source_set"):
            if not isinstance(row.get(field), str) or not row[field]:
                errors.append(prefix + "missing_" + field)
        digest = row.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(prefix + "invalid_sha256")
        if row.get("image_kind") != "raw_unannotated":
            errors.append(prefix + "annotated_or_generated_input_forbidden")
        if row.get("near_duplicate_audited") is not True:
            errors.append(prefix + "near_duplicate_audit_required")
        reviewers = row.get("reviewers")
        reviewers_valid = isinstance(reviewers, list) and all(isinstance(x, str) and x.strip() for x in reviewers)
        if row.get("review_status") not in {"dual_agreed", "adjudicated"} or not reviewers_valid or len(set(reviewers)) < 2:
            errors.append(prefix + "two_independent_human_reviews_required")
        if row.get("label_source") not in {"human", "teacher_human_corrected"}:
            errors.append(prefix + "unverified_pseudolabel_forbidden")
        if row.get("label_source") == "teacher_human_corrected" and not row.get("teacher_output_training_rights_confirmed"):
            errors.append(prefix + "teacher_rights_unconfirmed")
        if split in {"train", "dev"}:
            if row.get("training_rights_confirmed") is not True:
                errors.append(prefix + "training_rights_unconfirmed")
            if row.get("evaluation_only") is not False:
                errors.append(prefix + "evaluation_only_cannot_train_or_tune")
            if row.get("source_set") == "existing_user_review_v2":
                errors.append(prefix + "existing_review_set_stays_regression")
        width, height = row.get("width"), row.get("height")
        dimensions_valid = all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height))
        if not dimensions_valid:
            errors.append(prefix + "invalid_dimensions")
        if row.get("all_visible_trucks_labeled") is not True:
            errors.append(prefix + "incomplete_object_supervision")
        vehicles = row.get("vehicles")
        if not isinstance(vehicles, list):
            errors.append(prefix + "vehicles_must_be_list")
            vehicles = []
        total = row.get("count")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0 or total != len(vehicles):
            errors.append(prefix + "count_object_list_mismatch")
        observation_ids = set()
        for obj in vehicles:
            oid = obj.get("observation_id")
            if not isinstance(oid, str) or not oid or oid in observation_ids:
                errors.append(prefix + "duplicate_or_missing_observation_id")
            observation_ids.add(oid)
            box = obj.get("bbox_px")
            valid_box = isinstance(box, list) and len(box) == 4 and all(finite_number(x) for x in box)
            if valid_box and dimensions_valid:
                valid_box = 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height
            if not valid_box:
                errors.append(prefix + "invalid_bbox")
            if obj.get("type") not in {"large", "medium", "small", "unknown"}:
                errors.append(prefix + "invalid_type")
            if obj.get("type") != "unknown" and obj.get("type_human_confirmed") is not True:
                errors.append(prefix + "unverified_type")
            if obj.get("visibility") not in {"full", "partial"}:
                errors.append(prefix + "not_currently_visible")
            if not obj.get("evidence"):
                errors.append(prefix + "missing_current_evidence")
            if not obj.get("vehicle_session_id"):
                errors.append(prefix + "vehicle_group_needed_for_leakage_audit")
            else:
                group_splits[("vehicle", obj["vehicle_session_id"])].add(split)
        session = row.get("capture_session_id")
        for kind, value in (("hash", digest), ("near", row.get("near_duplicate_group")),
                            ("block", (session, row.get("time_block"))), ("derived", row.get("derivation_root"))):
            if value:
                group_splits[(kind, str(value))].add(split)
        start, end = row.get("context_start_s"), row.get("context_end_s")
        if not all(finite_number(x) for x in (start, end)) or start < 0 or start > end:
            errors.append(prefix + "invalid_context_interval")
        else:
            valid_intervals.append((session, start, end, split, sid))
    for group, splits in group_splits.items():
        if len(splits) > 1:
            errors.append(f"cross_split_group:{group[0]}:{group[1]}:{sorted(splits)}")
    for i, (session, start, end, split, sid) in enumerate(valid_intervals):
        for other_session, other_start, other_end, other_split, other_sid in valid_intervals[i + 1:]:
            if session == other_session and split != other_split and max(start, other_start) <= min(end, other_end) + guard_s:
                errors.append(f"cross_split_temporal_guard:{sid}:{other_sid}")
    return sorted(set(errors))


def verify_media(rows, media_root):
    """Read only the exact manifest images after resolving them within one allowed root."""
    from PIL import Image

    root = Path(media_root).resolve(strict=True)
    for row in rows:
        path = (root / row["image"]).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"outside_media_root:{row['sample_id']}")
        if not path.is_file():
            raise ValueError(f"not_file:{row['sample_id']}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"media_hash_mismatch:{row['sample_id']}")
        with Image.open(path) as image:
            if image.size != (row["width"], row["height"]):
                raise ValueError(f"media_dimensions_mismatch:{row['sample_id']}")
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError(f"unsupported_image_format:{row['sample_id']}")


def export_row(row):
    if row["split"] not in {"train", "dev"}:
        raise ValueError(f"cannot_export_evaluation_split:{row['sample_id']}")
    vehicles = []
    for i, obj in enumerate(row["vehicles"]):
        width, height = row["width"], row["height"]
        box = [round(x / denom * 1000) for x, denom in zip(obj["bbox_px"], [width, height, width, height])]
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError(f"bbox_quantization_collapse:{row['sample_id']}")
        vehicles.append({"local_id": f"o{i + 1}", "bbox_2d": box, "type": obj["type"],
                         "visibility": obj["visibility"], "evidence": obj["evidence"]})
    answer = json.dumps({"total": len(vehicles), "vehicles": vehicles}, ensure_ascii=False, separators=(",", ":"))
    return {"image": row["image"], "conversations": [{"from": "human", "value": PROMPT}, {"from": "gpt", "value": answer}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Canonical JSONL, including all splits for leakage audit")
    parser.add_argument("--guard-s", type=float, default=60)
    parser.add_argument("--export-dir", type=Path, help="Optional NEW directory; only train/dev are exported")
    parser.add_argument("--media-root", type=Path, help="Required for export; manifest image paths must stay inside")
    args = parser.parse_args()
    if not math.isfinite(args.guard_s) or args.guard_s < 0:
        parser.error("guard-s must be finite and nonnegative")
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not rows:
        parser.error("empty dataset")
    errors = validate(rows, args.guard_s)
    print(json.dumps({"records": len(rows), "errors": errors, "accuracy": "unmeasured", "model_calls": 0}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(2)
    if args.export_dir:
        if not args.media_root:
            parser.error("export requires media-root")
        verify_media(rows, args.media_root)
        outputs = {split: [export_row(row) for row in rows if row["split"] == split] for split in ("train", "dev")}
        args.export_dir.mkdir(parents=False, exist_ok=False)
        for split, data in outputs.items():
            (args.export_dir / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data), encoding="utf-8")
        audit = {"source_manifest_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
                 "guard_s": args.guard_s, "train_N": len(outputs["train"]), "dev_N": len(outputs["dev"]),
                 "blind_exported": False, "regression_exported": False, "training_started": False}
        (args.export_dir / "export_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
