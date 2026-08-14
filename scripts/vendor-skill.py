#!/usr/bin/env python3
"""Vendor this repository's released Skill into another repository."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


NAME = "evolve-software-architecture"
SOURCE_URL = "https://github.com/qinyu765/evolve-software-architecture"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def repo_root(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path, help="target repository")
    parser.add_argument("--ref", default="HEAD", help="release tag or commit to record")
    parser.add_argument("--check", action="store_true", help="compare without writing")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    target = repo_root(args.target.expanduser().resolve())
    package = source / "skills" / NAME
    destination = target / ".agents" / "skills" / NAME
    lock_path = target / ".agents" / "vendor-lock.json"
    if target == Path("/") or target == Path.home():
        raise SystemExit("refusing an unsafe target repository")
    if not package.is_dir():
        raise SystemExit(f"missing source package: {package}")

    commit = git(source, "rev-parse", args.ref)
    if args.check:
        if not destination.is_dir():
            raise SystemExit(f"missing vendor destination: {destination}")
        with tempfile.TemporaryDirectory() as temp:
            expected = Path(temp) / NAME
            shutil.copytree(package, expected)
            result = subprocess.run(["diff", "-ru", str(expected), str(destination)], check=False)
            if result.returncode:
                raise SystemExit("vendor copy differs from the current source package")
        print(f"vendor copy is current: {destination}")
        return 0

    if destination.exists():
        raise SystemExit(f"refusing to overwrite existing vendor copy: {destination}; remove it only after review")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, destination)
    locks = {}
    if lock_path.exists():
        locks = json.loads(lock_path.read_text(encoding="utf-8"))
    locks[NAME] = {
        "source": SOURCE_URL,
        "version": args.ref,
        "commit": commit,
        "package": f"skills/{NAME}",
    }
    lock_path.write_text(json.dumps(locks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"vendored {NAME} at {args.ref} ({commit}) into {destination}")
    print(f"updated {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
