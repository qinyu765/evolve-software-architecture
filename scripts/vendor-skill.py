#!/usr/bin/env python3
"""Vendor an exact released Skill package into another repository."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from vendor_lib import (
    NAME,
    PACKAGE_PATH,
    SOURCE_URL,
    assert_tree_matches,
    locked_commit,
    materialize_package,
    read_locks,
    release_commit,
    replace_tree,
    repo_root,
    write_locks,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path, help="target repository")
    parser.add_argument("--ref", help="annotated SemVer release tag to install")
    parser.add_argument("--check", action="store_true", help="verify the locked copy")
    parser.add_argument(
        "--update",
        action="store_true",
        help="replace an unchanged locked copy with the selected release",
    )
    args = parser.parse_args()
    if args.check and args.update:
        parser.error("--check and --update cannot be combined")
    if not args.check and not args.ref:
        parser.error("--ref is required for install or update")

    source = Path(__file__).resolve().parents[1]
    target = repo_root(args.target.expanduser().resolve())
    destination = target / ".agents" / "skills" / NAME
    lock_path = target / ".agents" / "vendor-lock.json"
    if target == Path("/") or target == Path.home():
        raise SystemExit("refusing an unsafe target repository")

    locks = read_locks(lock_path)
    if args.check:
        entry = locks.get(NAME)
        if not entry:
            raise SystemExit(f"missing {NAME} entry in {lock_path}")
        commit, legacy_tag_object = locked_commit(source, entry)
        with tempfile.TemporaryDirectory() as temp:
            expected = materialize_package(source, commit, Path(temp))
            assert_tree_matches(expected, destination)
        suffix = " (legacy tag-object lock)" if legacy_tag_object else ""
        print(f"vendor copy matches {entry['version']} at {commit}{suffix}")
        return 0

    commit = release_commit(source, args.ref)
    if destination.exists() and not args.update:
        raise SystemExit(
            f"refusing to overwrite existing vendor copy: {destination}; use --update after review"
        )

    with tempfile.TemporaryDirectory() as released_temp:
        released = materialize_package(source, commit, Path(released_temp))
        if args.update:
            entry = locks.get(NAME)
            if not entry:
                raise SystemExit(f"missing {NAME} entry in {lock_path}")
            previous_commit, _ = locked_commit(source, entry)
            with tempfile.TemporaryDirectory() as previous_temp:
                previous = materialize_package(source, previous_commit, Path(previous_temp))
                assert_tree_matches(previous, destination)
        replace_tree(released, destination)

    locks[NAME] = {
        "source": SOURCE_URL,
        "version": args.ref,
        "commit": commit,
        "package": PACKAGE_PATH,
    }
    write_locks(lock_path, locks)
    print(f"vendored {NAME} at {args.ref} ({commit}) into {destination}")
    print(f"updated {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
