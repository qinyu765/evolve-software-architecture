#!/usr/bin/env python3
"""Validate the repository's installable Skill and its public contract."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


NAME = "evolve-software-architecture"


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    skill = root / "skills" / NAME
    skill_md = skill / "SKILL.md"
    metadata = skill / "agents" / "openai.yaml"
    if not skill_md.is_file():
        fail(f"missing {skill_md}")
    if not metadata.is_file():
        fail(f"missing {metadata}")

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    closing = content.find("\n---\n", 4)
    if closing < 0:
        fail("SKILL.md frontmatter is not closed")
    frontmatter = content[4:closing]
    name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", frontmatter, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not name_match or name_match.group(1) != NAME:
        fail("SKILL.md name must match its directory")
    if not description_match or len(description_match.group(1).strip()) < 80:
        fail("SKILL.md description must explain capability and triggers")
    if len(content.splitlines()) > 500:
        fail("SKILL.md must stay under 500 lines")
    for relative in [
        "references/core/assessment-framework.md",
        "references/core/quality-attributes.md",
        "references/core/decision-record.md",
        "references/project-types/project-type-selection.md",
        "references/project-types/desktop-tauri.md",
    ]:
        if not (skill / relative).is_file():
            fail(f"missing required reference: {relative}")
    print(f"valid: {skill}")
    print(f"lines: {len(content.splitlines())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
