#!/usr/bin/env python3
"""Vendor this repository's released Skill into another repository."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tarfile
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


def materialize_package(repo: Path, ref: str, destination: Path) -> Path:
    """Materialize one historical package into a temporary directory."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", ref, f"skills/{NAME}"],
        cwd=repo,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination)
    return destination / "skills" / NAME


def assert_matches(repo: Path, ref: str, actual: Path, temp_root: Path) -> None:
    expected = materialize_package(repo, ref, temp_root)
    result = subprocess.run(["diff", "-ru", str(expected), str(actual)], check=False)
    if result.returncode:
        raise SystemExit(
            "existing vendor copy differs from its locked source; refusing to overwrite local changes"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path, help="target repository")
    parser.add_argument("--ref", default="HEAD", help="release tag or commit to record")
    parser.add_argument("--check", action="store_true", help="compare without writing")
    parser.add_argument(
        "--update",
        action="store_true",
        help="safely replace an existing copy whose locked version is unchanged locally",
    )
    args = parser.parse_args()

    if args.check and args.update:
        parser.error("--check and --update cannot be combined")

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

    locks = {}
    if lock_path.exists():
        locks = json.loads(lock_path.read_text(encoding="utf-8"))

    if destination.exists() and not args.update:
        raise SystemExit(
            f"refusing to overwrite existing vendor copy: {destination}; use --update after review"
        )
    if args.update:
        previous = locks.get(NAME, {})
        previous_ref = previous.get("commit") or previous.get("version")
        if not previous_ref:
            raise SystemExit("cannot update without a locked source commit or version")
        with tempfile.TemporaryDirectory() as temp:
            assert_matches(source, previous_ref, destination, Path(temp))
        shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, destination)
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
