"""Write hashes for the frozen gold set, prompts and model responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from model_client import ROOT


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    patterns = [
        "data/gold/temporal_gold.json",
        "data/frame_manifest.json",
        "data/candidates.json",
        "data/results/metrics.json",
        "data/results/per_observation.csv",
        "data/runs/primary/*.json",
        "data/runs/confirm/*.json",
        "data/runs/pair_probes/*.json",
        "scripts/*.py",
        "research/temporal_reid/ROUTE_REPORT.md",
    ]
    files: dict[str, dict[str, str | int]] = {}
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                files[path.relative_to(ROOT).as_posix()] = {
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                }
    payload = {
        "algorithm": "sha256",
        "purpose": "immutable fingerprint of the frozen development evidence",
        "files": files,
    }
    output = ROOT / "data" / "results" / "evidence_manifest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(files)} hashes to {output}")


if __name__ == "__main__":
    main()
