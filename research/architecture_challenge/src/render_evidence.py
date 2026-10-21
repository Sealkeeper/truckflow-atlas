"""Render saved final candidates back onto frames for visual review.

This is evidence rendering only. It never changes counts or vehicle identity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import EVIDENCE, RUNS, annotation_image, frame_path


ARCHITECTURES = ("bands", "windows", "tree", "scene_graph", "critic")


def render_one(architecture: str, run_path: Path) -> Path | None:
    payload: dict[str, Any] = json.loads(run_path.read_text(encoding="utf-8"))
    vehicles = payload.get("final_vehicles") or []
    camera = payload["camera"]
    time_s = int(payload["time"])
    source = frame_path(camera, time_s)
    out = EVIDENCE / architecture / f"{camera}_{time_s}" / "final_annotated.jpg"
    annotation_image(source, vehicles, out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architectures", default=",".join(ARCHITECTURES))
    args = parser.parse_args()
    for architecture in (item.strip() for item in args.architectures.split(",")):
        run_dir = RUNS / architecture
        for run_path in sorted(run_dir.glob("*.json")):
            if run_path.name.startswith("_"):
                continue
            out = render_one(architecture, run_path)
            if out:
                print(out)


if __name__ == "__main__":
    main()
