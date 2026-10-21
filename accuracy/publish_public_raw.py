"""Publish frozen raw responses byte-for-byte to the shared coord directory.

No model call, no JSON rewrite.  The 4 C fallback responses are already
embedded in their parent raw JSON at calls[1]; this script records their
canonical sub-object hash instead of duplicating or modifying the raw file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "accuracy" / "runs" / "single_pass_v1"
PUBLIC = Path(
    r"D:\File\PROJECT\codex\codex-货车\all-sessions-can-see\coord\exploration\single-pass"
)
RAW_ROOT = PUBLIC / "raw"
TAGS = {
    "A_full": ("r1", "r2", "r3"),
    "B_aisle": ("r1", "r2", "r3"),
    "C_adaptive": ("r1", "r2", "r3"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_dir(config: str, tag: str) -> Path:
    return SOURCE_ROOT / (config if tag == "r1" else f"{config}_{tag}") / "doubao"


def current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    commit = current_commit()
    runs = []
    total_files = 0
    total_bytes = 0
    fallback_files = []
    public_path_by_source: dict[str, str] = {}
    for config, tags in TAGS.items():
        for tag in tags:
            src_dir = source_dir(config, tag)
            dst_dir = RAW_ROOT / config / tag
            dst_dir.mkdir(parents=True, exist_ok=True)
            files = []
            for src in sorted(src_dir.glob("*.json")):
                if src.name.startswith("summary"):
                    continue
                dst = dst_dir / src.name
                shutil.copyfile(src, dst)
                src_hash = sha256(src)
                dst_hash = sha256(dst)
                if src_hash != dst_hash:
                    raise SystemExit(f"hash mismatch: {src} -> {dst}")
                payload = json.loads(src.read_text(encoding="utf-8"))
                calls = payload.get("calls") or []
                fallback_calls = [
                    {
                        "call_index": index,
                        "kind": call.get("kind"),
                        "http_requests": call.get("http_requests"),
                        "latency_s": call.get("latency_s"),
                        "ok": call.get("ok"),
                        "parse_ok": call.get("parse_ok"),
                        "canonical_sha256": hashlib.sha256(
                            json.dumps(
                                call, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                            ).encode("utf-8")
                        ).hexdigest(),
                    }
                    for index, call in enumerate(calls)
                    if call.get("kind") == "far_zoom"
                ]
                entry = {
                    "sample_id": payload["sample_id"],
                    "truth": payload["truth"],
                    "predicted_count": payload["predicted_count"],
                    "error": payload["error"],
                    "call_count": payload["call_count"],
                    "source": str(src.relative_to(ROOT)),
                    "destination": str(dst.relative_to(PUBLIC)),
                    "source_sha256": src_hash,
                    "destination_sha256": dst_hash,
                    "bytes": src.stat().st_size,
                    "byte_identical": True,
                    "fallback_embedded": bool(fallback_calls),
                    "fallback_calls": fallback_calls,
                }
                files.append(entry)
                total_files += 1
                total_bytes += entry["bytes"]
                public_path_by_source[entry["source"]] = entry["destination"]
                if fallback_calls:
                    fallback_files.append({"sample_id": payload["sample_id"], **entry})
            if len(files) != 20:
                raise SystemExit(f"{config}/{tag}: expected 20 raw files, got {len(files)}")
            runs.append(
                {
                    "config": config,
                    "run": tag,
                    "file_count": len(files),
                    "files": files,
                }
            )

    if total_files != 180:
        raise SystemExit(f"expected 180 raw files, got {total_files}")
    if len(fallback_files) != 4:
        raise SystemExit(f"expected 4 embedded fallback calls, got {len(fallback_files)}")

    manifest = {
        "schema": "single-pass-raw-manifest-v1",
        "commit": commit,
        "created_date": "2026-10-21",
        "copy_mode": "byte-for-byte; no JSON rewrite",
        "source_worktree": str(ROOT),
        "public_root": str(PUBLIC),
        "model": "doubao ep-20260828174616-dthpx",
        "totals": {
            "runs": len(runs),
            "raw_files": total_files,
            "raw_bytes": total_bytes,
            "fallback_embedded": len(fallback_files),
            "fallback_separate_files": 0,
        },
        "fallback_note": (
            "The 4 C fallback responses are embedded in the same copied raw JSON "
            "at calls[1]; they are not separate files. The full-file SHA-256 covers "
            "them, and fallback_calls[].canonical_sha256 hashes the exact embedded "
            "call object without modifying the raw JSON."
        ),
        "runs": runs,
    }
    (PUBLIC / "RAW_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Add public raw paths to the existing index without changing any raw file.
    index_path = PUBLIC / "RUNS_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["public_raw_root"] = "raw/"
    index["raw_manifest"] = "RAW_MANIFEST.json"
    for run in index["runs"]:
        for sample in run["samples"]:
            public_path = public_path_by_source.get(sample["raw_file"])
            if public_path is None:
                raise SystemExit(f"public raw path missing for {sample['raw_file']}")
            sample["public_raw_file"] = public_path
            sample["public_raw_sha256"] = sample["raw_sha256"]
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    attempts_path = PUBLIC / "ATTEMPTS.json"
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    attempts["warning"] = (
        "3 early diagnostic calls were overwritten before the frozen run: 2 far-zone "
        "prompt-v1 diagnostics and 1 B prompt-v1 test. Their raw responses are "
        "unavailable; they were not reconstructed. Their counts remain in "
        "total_http_requests=189, but they are absent from RUNS_INDEX and RAW_MANIFEST."
    )
    attempts["evidence_completeness"] = {
        "frozen_primary_raw_copied": 180,
        "fallback_embedded": 4,
        "fallback_separate_files": 0,
        "discarded_unrecoverable": 3,
        "discarded_reconstructed": 0,
        "saved_far_probe_raw": 2,
    }
    attempts_path.write_text(
        json.dumps(attempts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"copied {total_files} files ({total_bytes} bytes), "
        f"embedded fallback={len(fallback_files)}, commit={commit}"
    )


if __name__ == "__main__":
    main()
