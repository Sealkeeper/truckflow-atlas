from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from model_probe import ENV_PATH, PROMPT, load_env, probe


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern", default="assets/frames/*.jpg")
    parser.add_argument("--models", default="doubao,aibox")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "accuracy" / "runs" / "batch")
    args = parser.parse_args()
    load_env(ENV_PATH)
    images = sorted(ROOT.glob(args.pattern))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    tasks = [(image, model) for image in images for model in args.models.split(",")]
    results: dict[str, dict] = {str(image): {"image": str(image), "runs": []} for image in images}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, model, image, PROMPT, 3000): (image, model) for image, model in tasks}
        for future in as_completed(futures):
            image, model = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"model": model, "ok": False, "error": repr(exc)}
            result["image"] = str(image)
            results[str(image)]["runs"].append(result)
            if result.get("ok"):
                counts = result["parsed"].get("counts", {})
                print(f"{image.name:22s} {model:8s} total={counts.get('total')} ({result['latency_s']}s)")
            else:
                print(f"{image.name:22s} {model:8s} FAILED {result.get('error')}")
    for image, payload in results.items():
        out = args.out_dir / (Path(image).stem + ".json")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(results)} result files to {args.out_dir}")


if __name__ == "__main__":
    main()
