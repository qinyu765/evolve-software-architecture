#!/usr/bin/env python3
"""Print a partial, read-only inventory; this is not a technology classifier."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [*args], cwd=repo, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="repository to inspect")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        parser.error(f"repository does not exist: {repo}")

    candidates = [
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "Cargo.toml",
        "package.json",
        "pyproject.toml",
        "go.mod",
        "docs/solution-design.md",
        "docs/roadmap.md",
    ]
    existing = [path for path in candidates if (repo / path).exists()]
    top_level = sorted(
        path.name for path in repo.iterdir() if path.name not in {".git", "node_modules"}
    )
    payload = {
        "inventory_scope": "top-level entries and a non-exhaustive file shortlist; inspect entry points and nested packages separately",
        "repository": str(repo),
        "branch": run(repo, "git", "branch", "--show-current"),
        "head": run(repo, "git", "rev-parse", "HEAD"),
        "recent_commits": run(repo, "git", "log", "-8", "--oneline").splitlines(),
        "tracked_file_count": run(repo, "git", "ls-files").count("\n") + 1
        if run(repo, "git", "ls-files")
        else 0,
        "candidate_files": existing,
        "top_level_entries": top_level,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
