"""Redact machine-local paths from public round-2 evaluation JSON.

Only string display values are changed. Numeric results, hashes, and list
contents remain intact. The caller supplies the public results directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TEMP_PATH = re.compile(
    r"[A-Z]:\\(?:[^\\]+\\){2,}AppData\\Local\\Temp\\[^\"\\]+",
    flags=re.IGNORECASE,
)
SECRET_NAMES = re.compile(
    r"(?i)ARK_API_KEY|Authorization|Bearer\s+|password|client_secret"
)


def _prefix_variants(root: Path) -> tuple[str, ...]:
    value = str(root)
    return tuple({value + "\\", value + "/"})


def sanitize(
    value: Any,
    *,
    repo_root: Path,
    workspace_root: Path,
) -> tuple[Any, int]:
    if isinstance(value, str):
        cleaned = TEMP_PATH.sub("private://redacted-temp", value)
        for prefix in _prefix_variants(repo_root):
            cleaned = cleaned.replace(prefix, "repo://")
        for prefix in _prefix_variants(workspace_root):
            cleaned = cleaned.replace(prefix, "workspace://")
        return cleaned, int(cleaned != value)
    if isinstance(value, list):
        rows = [
            sanitize(
                item,
                repo_root=repo_root,
                workspace_root=workspace_root,
            )
            for item in value
        ]
        return [item for item, _ in rows], sum(changed for _, changed in rows)
    if isinstance(value, dict):
        result = {}
        changed_count = 0
        for key, item in value.items():
            cleaned, changed = sanitize(
                item,
                repo_root=repo_root,
                workspace_root=workspace_root,
            )
            result[key] = cleaned
            changed_count += changed
        return result, changed_count
    return value, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args()
    results_dir = args.results_dir.resolve()
    repo_root = results_dir.parents[3].resolve()
    workspace_root = repo_root.parent.resolve()

    files = sorted(results_dir.glob("*.json"))
    total_changes = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        cleaned, changes = sanitize(
            document,
            repo_root=repo_root,
            workspace_root=workspace_root,
        )
        total_changes += changes
        path.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    leaks = []
    private_prefixes = (
        *_prefix_variants(repo_root),
        *_prefix_variants(workspace_root),
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        if any(prefix in text for prefix in private_prefixes) or TEMP_PATH.search(text):
            leaks.append(f"{path.name}: private absolute path remains")
        if SECRET_NAMES.search(text):
            leaks.append(f"{path.name}: secret-like field remains")
    if leaks:
        raise SystemExit("\n".join(leaks))

    print(f"sanitized_json_files={len(files)} changed_strings={total_changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
