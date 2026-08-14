#!/usr/bin/env python3
"""Shared primitives for reproducible, release-pinned Skill vendoring."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


NAME = "evolve-software-architecture"
PACKAGE_PATH = f"skills/{NAME}"
SOURCE_URL = "https://github.com/qinyu765/evolve-software-architecture"
SEMVER_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def repo_root(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve()


def release_commit(repo: Path, version: str) -> str:
    if not SEMVER_TAG.fullmatch(version):
        raise SystemExit(f"release ref must be a SemVer tag such as v0.1.2: {version}")
    tag_ref = f"refs/tags/{version}"
    if git(repo, "cat-file", "-t", tag_ref) != "tag":
        raise SystemExit(f"release ref must be an annotated tag: {version}")
    return git(repo, "rev-parse", f"{tag_ref}^{{commit}}")


def locked_commit(repo: Path, entry: dict[str, str]) -> tuple[str, bool]:
    version = entry.get("version", "")
    recorded = entry.get("commit", "")
    peeled = release_commit(repo, version)
    if recorded == peeled:
        return peeled, False

    # v0.1.0 and v0.1.1 accidentally recorded the annotated tag object's SHA.
    tag_object = git(repo, "rev-parse", f"refs/tags/{version}")
    if recorded == tag_object:
        return peeled, True
    raise SystemExit(
        f"vendor lock commit does not match {version}: recorded {recorded}, expected {peeled}"
    )


def materialize_package(repo: Path, ref: str, destination: Path) -> Path:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", ref, PACKAGE_PATH],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if archive.returncode:
        raise SystemExit(archive.stderr.decode("utf-8", errors="replace").strip())

    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise SystemExit(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk():
                raise SystemExit(f"release package must not contain links: {member.name}")
        bundle.extractall(destination)
    return destination / PACKAGE_PATH


def tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise SystemExit(f"missing directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def assert_tree_matches(expected: Path, actual: Path) -> None:
    expected_hash = tree_digest(expected)
    actual_hash = tree_digest(actual)
    if expected_hash != actual_hash:
        raise SystemExit(
            "existing vendor copy differs from its locked source; refusing to overwrite "
            f"local changes (expected {expected_hash}, got {actual_hash})"
        )


def read_locks(lock_path: Path) -> dict[str, dict[str, str]]:
    if not lock_path.is_file():
        return {}
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"invalid vendor lock: {lock_path}")
    return data


def replace_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{NAME}-stage-", dir=destination.parent)
    )
    staged = staging_root / NAME
    backup = destination.parent / f".{NAME}-backup"
    if backup.exists():
        raise SystemExit(f"stale vendor backup requires review: {backup}")
    try:
        shutil.copytree(source, staged)
        if destination.exists():
            destination.rename(backup)
        staged.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup)


def write_locks(lock_path: Path, locks: dict[str, dict[str, str]]) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(locks, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=lock_path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(lock_path)
