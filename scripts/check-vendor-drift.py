#!/usr/bin/env python3
"""Check a XiLuoLin-style vendor copy without changing either repository."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path
import shutil


NAME = "evolve-software-architecture"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "skills" / NAME
    target = args.target.expanduser().resolve()
    destination = target / ".agents" / "skills" / NAME
    if not destination.is_dir():
        print(f"missing vendor copy: {destination}")
        return 1
    with tempfile.TemporaryDirectory() as temp:
        expected = Path(temp) / NAME
        shutil.copytree(source, expected)
        result = subprocess.run(["diff", "-ru", str(expected), str(destination)], check=False)
    if result.returncode:
        print("vendor drift detected")
        return 1
    print("vendor copy matches source package")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
