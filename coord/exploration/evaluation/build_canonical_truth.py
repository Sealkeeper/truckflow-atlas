"""Publish a canonical per-time truth content hash and compare published sources.

File hashes differ when the same labels are serialized differently. The
canonical hash covers the label content only: time, north, south, overlap,
unique. No label is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def from_user_truth(path: Path) -> dict[int, dict[str, int]]:
    doc = load(path)
    out: dict[int, dict[str, int]] = {}
    for sample in doc["samples"]:
        time_s = int(sample["time"])
        counts = sample["camera_counts"]
        out[time_s] = {
            "north": int(counts["north"]),
            "south": int(counts["south"]),
            "overlap": int(sample["overlap"]),
            "unique": int(sample["unique_total"]),
        }
    return out


def from_joint_metrics(path: Path) -> dict[int, dict[str, int]]:
    doc = load(path)
    out: dict[int, dict[str, int]] = {}
    for row in doc["camera_counts"]["rows"]:
        camera, seconds = row["key"].split("_", 1)
        time_s = int(seconds)
        out.setdefault(time_s, {})[camera] = int(row["truth"])
    for row in doc["unique_counts"]["rows"]:
        out.setdefault(int(row["time"]), {})["unique"] = int(row["truth"])
    for row in doc["overlap_counts"]["rows"]:
        out.setdefault(int(row["time"]), {})["overlap"] = int(row["truth"])
    return out


def canonical_payload(times: dict[int, dict[str, int]]) -> list[dict[str, int]]:
    return [
        {
            "time": time_s,
            "north": times[time_s]["north"],
            "south": times[time_s]["south"],
            "overlap": times[time_s]["overlap"],
            "unique": times[time_s]["unique"],
        }
        for time_s in sorted(times)
    ]


def canonical_bytes(times: dict[int, dict[str, int]]) -> bytes:
    return json.dumps(
        canonical_payload(times),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compare(
    reference: dict[int, dict[str, int]], other: dict[int, dict[str, int]]
) -> dict[str, Any]:
    mismatches = []
    for time_s in sorted(reference):
        if time_s not in other:
            mismatches.append({"time": time_s, "field": "all", "other": None})
            continue
        for field in ("north", "south", "overlap", "unique"):
            if reference[time_s][field] != other[time_s].get(field):
                mismatches.append(
                    {
                        "time": time_s,
                        "field": field,
                        "reference": reference[time_s][field],
                        "other": other[time_s].get(field),
                    }
                )
    return {"match": not mismatches, "mismatches": mismatches}


def validate(times: dict[int, dict[str, int]], label: str) -> None:
    if len(times) != 10:
        raise SystemExit(f"{label}: expected 10 times, found {len(times)}")
    for time_s, row in times.items():
        if set(row) != {"north", "south", "overlap", "unique"}:
            raise SystemExit(f"{label} t{time_s}: incomplete fields {row}")
        if row["north"] + row["south"] - row["overlap"] != row["unique"]:
            raise SystemExit(f"{label} t{time_s}: unique formula mismatch {row}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-truth", type=Path, required=True)
    parser.add_argument("--joint-metrics", type=Path, required=True)
    parser.add_argument("--event-metrics", type=Path, required=True)
    parser.add_argument("--attachment-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reference = from_user_truth(args.user_truth)
    joint = from_joint_metrics(args.joint_metrics)
    validate(reference, "user truth")
    validate(joint, "joint metrics")
    joint_check = compare(reference, joint)

    event_doc = load(args.event_metrics)
    event_rows = {
        int(round(row["time_s"])): int(row["truth"]) for row in event_doc["rows"]
    }
    event_mismatches = [
        {"time": time_s, "reference": reference[time_s]["north" if camera == "north" else "south"], "event": truth}
        for row in event_doc["rows"]
        for camera, time_s, truth in [
            (row["camera"], int(round(row["time_s"])), int(row["truth"]))
        ]
        if reference[time_s][camera] != truth
    ]
    event_check = {"match": not event_mismatches, "mismatches": event_mismatches}

    attachment_doc = load(args.attachment_manifest)
    attachment_counts = []
    attachment_mismatches = []
    for record in attachment_doc.get("records", []):
        minutes, seconds = (int(part) for part in record["time"].split(":"))
        time_s = minutes * 60 + seconds
        camera = record["camera"]
        count = int(record["marked_vehicle_count"])
        attachment_counts.append(
            {"time": time_s, "camera": camera, "count": count, "file": record["file"]}
        )
        if reference[time_s][camera] != count:
            attachment_mismatches.append(
                {
                    "time": time_s,
                    "camera": camera,
                    "reference": reference[time_s][camera],
                    "attachment": count,
                }
            )
    attachment_check = {
        "match": not attachment_mismatches,
        "mismatches": attachment_mismatches,
        "annotated_samples": len(attachment_counts),
    }

    payload = {
        "schema": "truckflow-canonical-truth-v1",
        "definition": (
            "per-time canonical labels: north and south visible truck counts, "
            "cross-camera overlap count, and unique count"
        ),
        "canonicalization": (
            "JSON array sorted by time; each item has time,north,south,overlap,unique; "
            "sort_keys=true, separators=(',',':'), UTF-8"
        ),
        "canonical_sha256": hashlib.sha256(canonical_bytes(reference)).hexdigest(),
        "source_files": {
            "user_truth": {
                "file": "accuracy/reviewed/user-final-review-v2-2026-10-21.json",
                "sha256": sha256_file(args.user_truth),
            },
            "joint_metrics": {
                "file": "coord/exploration/joint-multiview/metrics.json",
                "sha256": sha256_file(args.joint_metrics),
                "declared_label_sha256": load(args.joint_metrics).get("label_sha256"),
            },
            "event_metrics": {
                "file": "coord/exploration/event-ledger/metrics.json",
                "sha256": sha256_file(args.event_metrics),
            },
            "attachment_manifest": {
                "file": "review/user-attachments-20261021/manifest.json",
                "sha256": sha256_file(args.attachment_manifest),
            },
        },
        "times": canonical_payload(reference),
        "cross_checks": {
            "user_truth_vs_joint_metrics": joint_check,
            "user_truth_vs_event_subset": event_check,
            "user_truth_vs_attachment_manifest": attachment_check,
        },
        "attachment_subset": attachment_counts,
        "notes": [
            "The user truth file hash 735045... and the joint route's declared label hash c3fddc... are different files/serializations.",
            "Their canonical per-time label content matches; file-level hashes must not be compared as label content.",
            "No label or truth value was changed.",
        ],
    }
    if (
        not joint_check["match"]
        or not event_check["match"]
        or not attachment_check["match"]
    ):
        raise SystemExit("canonical truth mismatch; refusing to publish")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"canonical_sha256={payload['canonical_sha256']}")
    print(
        f"times={len(reference)} joint_match={joint_check['match']} "
        f"event_match={event_check['match']} "
        f"attachments_match={attachment_check['match']}"
    )
    print(f"out={args.out}")


if __name__ == "__main__":
    main()
