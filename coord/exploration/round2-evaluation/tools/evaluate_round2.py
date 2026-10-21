"""CLI for the strict round-2 route-output evaluator.

Example:
  python evaluate_round2.py --truth <truth.json> \
    --output <canonical-route-output.json> \
    --input-integrity <input-audit.json> \
    --out-json <result.json> --out-md <result.md>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core import (
    EvaluationError,
    evaluate_output,
    evaluation_markdown,
    load_canonical_output,
    load_json,
    write_json,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "independent"), default="dev")
    parser.add_argument("--baseline-exact", type=int, default=16)
    parser.add_argument("--input-integrity", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument(
        "--allow-contract-failure",
        action="store_true",
        help="Write diagnostics and exit zero even when the contract fails.",
    )
    args = parser.parse_args()

    try:
        output = load_canonical_output(args.output)
        integrity = load_json(args.input_integrity) if args.input_integrity else None
        if integrity is not None and "all_match" not in integrity:
            integrity = {
                "all_match": integrity.get("verification", {}).get("all_match"),
                "source": str(args.input_integrity.resolve()),
                "raw": integrity,
            }
        result = evaluate_output(
            args.truth.resolve(),
            output,
            split=args.split,
            input_integrity=integrity,
            baseline_exact=args.baseline_exact,
        )
    except EvaluationError as error:
        print(f"CONTRACT ERROR: {error}", file=sys.stderr)
        return 2

    write_json(args.out_json, result)
    write_text(args.out_md, evaluation_markdown(result))
    print(
        f"verdict={result['acceptance']['verdict']} "
        f"camera={result['camera_count']['headline']} "
        f"overlap={result['overlap']['headline']} "
        f"unique={result['unique']['headline']} "
        f"release_errors={result['release']['errors']}"
    )
    print(f"json={args.out_json.resolve()}")
    print(f"md={args.out_md.resolve()}")
    if (
        result["acceptance"]["verdict"] == "FAIL_CONTRACT"
        and not args.allow_contract_failure
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
