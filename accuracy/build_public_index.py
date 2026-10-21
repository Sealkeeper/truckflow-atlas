"""Build the public coord index for the frozen single-pass experiment.

This script does not call any model.  It only indexes already-saved raw JSON,
input hashes and aggregate metrics so another evaluator can audit every run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "accuracy" / "runs" / "single_pass_v1"
CROP_MANIFEST = ROOT / "accuracy" / "crops" / "single_pass_v1" / "manifest.json"
PUBLIC = Path(
    r"D:\File\PROJECT\codex\codex-货车\all-sessions-can-see\coord\exploration\single-pass"
)
def current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


COMMIT = current_commit()
MODEL = {
    "name": "doubao",
    "model_id": "ep-20260828174616-dthpx",
    "temperature": 0,
    "max_tokens": 3600,
    "images_per_call": 1,
    "retries": 0,
    "call_cap_per_frame": 2,
}
TAGS = {"A_full": ("r1", "r2", "r3"), "B_aisle": ("r1", "r2", "r3"), "C_adaptive": ("r1", "r2", "r3")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_dir(config: str, tag: str) -> Path:
    return RUN_ROOT / (config if tag == "r1" else f"{config}_{tag}") / "doubao"


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    crop_manifest = json.loads(CROP_MANIFEST.read_text(encoding="utf-8"))
    aggregate = json.loads((RUN_ROOT / "aggregate_doubao.json").read_text(encoding="utf-8"))

    runs = []
    total_primary = 0
    total_fallback = 0
    for config, tags in TAGS.items():
        for tag in tags:
            directory = run_dir(config, tag)
            rows = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(directory.glob("*.json"))
                if not path.name.startswith("summary")
            ]
            if len(rows) != 20:
                raise SystemExit(f"{config}/{tag}: expected 20 rows, got {len(rows)}")
            samples = []
            for path in sorted(directory.glob("*.json")):
                if path.name.startswith("summary"):
                    continue
                row = json.loads(path.read_text(encoding="utf-8"))
                samples.append(
                    {
                        "sample_id": row["sample_id"],
                        "truth": row["truth"],
                        "predicted_count": row["predicted_count"],
                        "error": row["error"],
                        "call_count": row["call_count"],
                        "triggered_far": row.get("triggered_far", False),
                        "latency_total_s": row["latency_total_s"],
                        "tokens_total": row["tokens_total"],
                        "failure": row.get("failure", False),
                        "prompt_sha256": row.get("prompt_sha256"),
                        "raw_file": str(path.relative_to(ROOT)),
                        "raw_sha256": sha256(path),
                    }
                )
            summary_path = directory.parent / "summary_doubao.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            primary = len(rows)
            fallback = sum(1 for row in rows if row.get("triggered_far"))
            total_primary += primary
            total_fallback += fallback
            runs.append(
                {
                    "config": config,
                    "tag": tag,
                    "directory": str(directory.relative_to(ROOT)),
                    "sample_count": len(rows),
                    "prompt_version": rows[0].get("prompt_version"),
                    "prompt_sha256": rows[0].get("prompt_sha256"),
                    "primary_calls": primary,
                    "fallback_calls": fallback,
                    "metrics": summary["summary"],
                    "metrics_file": str(summary_path.relative_to(ROOT)),
                    "metrics_sha256": sha256(summary_path),
                    "samples": samples,
                }
            )

    runs_index = {
        "schema": "single-pass-runs-index-v1",
        "route": "single-pass",
        "branch": "accuracy/single-pass",
        "commit": COMMIT,
        "model": MODEL,
        "truth": "accuracy/reviewed/user-final-review-v2-2026-10-21.json",
        "frozen_evaluation_calls": {
            "primary": total_primary,
            "fallback": total_fallback,
            "total": total_primary + total_fallback,
        },
        "runs": runs,
    }
    (PUBLIC / "RUNS_INDEX.json").write_text(
        json.dumps(runs_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    inputs = {
        "schema": "single-pass-inputs-v1",
        "aisle_box_pixels": crop_manifest["aisle_box_pixels"],
        "aisle_scale": crop_manifest["aisle_scale"],
        "far_fraction_of_aisle": crop_manifest["far_fraction_of_aisle"],
        "far_scale": crop_manifest["far_scale"],
        "videos": crop_manifest["videos"],
        "samples": [
            {
                "sample_id": sample["key"],
                "camera": sample["camera"],
                "time": sample["time"],
                "truth": sample["truth"],
                "full": sample["full"],
                "full_sha256": sample["full_sha256"],
                "aisle": sample["aisle"],
                "aisle_sha256": sample["aisle_sha256"],
                "far": sample["far"],
                "far_sha256": sample["far_sha256"],
            }
            for sample in crop_manifest["samples"]
        ],
    }
    (PUBLIC / "INPUTS.json").write_text(
        json.dumps(inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    attempts = {
        "schema": "single-pass-attempts-v1",
        "frozen_evaluation": {
            "A_full": 60,
            "B_aisle": 60,
            "C_adaptive": 64,
            "total": 184,
            "primary": 180,
            "conditional_fallback": 4,
        },
        "diagnostics": [
            {"name": "saved far-zone probe v2", "calls": 2, "saved": True},
            {"name": "discarded far-zone probe v1", "calls": 2, "saved": False},
            {"name": "discarded B north_600 prompt-v1 test", "calls": 1, "saved": False},
        ],
        "total_http_requests": 189,
        "retries": 0,
        "failed_requests": 0,
        "notes": [
            "Each HTTP request is one attempt; no transport retry.",
            "The three discarded calls were early prompt development before the frozen prompt; their raw responses were overwritten.",
            "All 180 frozen primary responses and all 4 C fallback responses are saved in RUNS_INDEX.json.",
        ],
    }
    (PUBLIC / "ATTEMPTS.json").write_text(
        json.dumps(attempts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "route": "single-pass",
        "branch": "accuracy/single-pass",
        "commit": COMMIT,
        "report": "accuracy/REPORT_single_pass_v1.md",
        "decision": {
            "keep": "B_aisle",
            "reject": ["A_full", "C_adaptive"],
            "reason": "B 18/20 exact in all 3 runs; C self-check misses 3 of 4 undercounts and adds false positives",
        },
        "model": MODEL,
        "frozen_evaluation_calls": runs_index["frozen_evaluation_calls"],
        "attempts_file": "ATTEMPTS.json",
        "inputs_file": "INPUTS.json",
        "runs_index_file": "RUNS_INDEX.json",
        "configs": {
            config: {
                "means": payload["means"],
                "runs": payload["runs"],
                "trigger_audit": payload["trigger_audit"],
                "aux_self_check_gate": payload["aux_self_check_gate"],
                "per_frame": payload["per_frame"],
            }
            for config, payload in aggregate["configs"].items()
        },
    }
    (PUBLIC / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("wrote RUNS_INDEX.json, INPUTS.json, ATTEMPTS.json, summary.json")


if __name__ == "__main__":
    main()
