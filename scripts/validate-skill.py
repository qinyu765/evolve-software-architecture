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
    frontmatter_keys = re.findall(r"^([a-zA-Z0-9_-]+):", frontmatter, re.MULTILINE)
    if frontmatter_keys != ["name", "description"]:
        fail("SKILL.md frontmatter must contain only name and description")
    name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", frontmatter, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not name_match or name_match.group(1) != NAME:
        fail("SKILL.md name must match its directory")
    if not description_match or len(description_match.group(1).strip()) < 80:
        fail("SKILL.md description must explain capability and triggers")
    if len(content.splitlines()) > 500:
        fail("SKILL.md must stay under 500 lines")
    forbidden = ["README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md"]
    for name in forbidden:
        if (skill / name).exists():
            fail(f"installable Skill contains repository documentation: {name}")
    for relative in [
        "references/core/assessment-framework.md",
        "references/core/quality-attributes.md",
        "references/core/decision-record.md",
        "references/project-types/project-type-selection.md",
        "references/project-types/desktop-tauri.md",
    ]:
        if not (skill / relative).is_file():
            fail(f"missing required reference: {relative}")
    for target in re.findall(r"\]\(([^)]+)\)", content):
        if target.startswith(("http://", "https://", "#")):
            continue
        resolved = (skill / target.split("#", 1)[0]).resolve()
        if skill.resolve() not in resolved.parents or not resolved.exists():
            fail(f"broken or unsafe SKILL.md link: {target}")

    metadata_content = metadata.read_text(encoding="utf-8")
    display = re.search(r'^\s+display_name:\s+"([^"]+)"$', metadata_content, re.MULTILINE)
    short = re.search(r'^\s+short_description:\s+"([^"]+)"$', metadata_content, re.MULTILINE)
    prompt = re.search(r'^\s+default_prompt:\s+"([^"]+)"$', metadata_content, re.MULTILINE)
    if not display or not short or not prompt:
        fail("agents/openai.yaml is missing quoted interface metadata")
    if not 25 <= len(short.group(1)) <= 64:
        fail("openai.yaml short_description must be 25-64 characters")
    if f"${NAME}" not in prompt.group(1):
        fail("openai.yaml default_prompt must mention the skill explicitly")
    print(f"valid: {skill}")
    print(f"lines: {len(content.splitlines())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
