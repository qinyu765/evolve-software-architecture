#!/usr/bin/env python3
"""Verify a project copy against the exact release recorded in its vendor lock."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from vendor_lib import (
    NAME,
    assert_tree_matches,
    locked_commit,
    materialize_package,
    read_locks,
    repo_root,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    target = repo_root(args.target.expanduser().resolve())
    destination = target / ".agents" / "skills" / NAME
    lock_path = target / ".agents" / "vendor-lock.json"
    entry = read_locks(lock_path).get(NAME)
    if not entry:
        raise SystemExit(f"missing {NAME} entry in {lock_path}")
    commit, legacy_tag_object = locked_commit(source, entry)
    with tempfile.TemporaryDirectory() as temp:
        expected = materialize_package(source, commit, Path(temp))
        assert_tree_matches(expected, destination)
    suffix = " (legacy tag-object lock)" if legacy_tag_object else ""
    print(f"vendor copy matches {entry['version']} at {commit}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
