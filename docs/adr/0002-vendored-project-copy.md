# ADR-0002: Commit a release-pinned project copy

- Status: accepted
- Date: 2026-08-14
- Scope: XiLuoLin integration

## Context

Codex discovers repository-scoped Skills under `.agents/skills`, and XiLuoLin already exposes that directory to Claude through `.claude -> .agents`. A sibling-repository symlink works only on the maintainer's machine. A submodule would introduce an extra clone and make the installable package layout less direct.

## Decision drivers

- every XiLuoLin clone should have the Skill available;
- the project should review updates as ordinary source changes;
- the upstream version must be auditable and reproducible;
- local modifications must never be silently overwritten.

## Options considered

1. Commit a copy of the released Skill and record its source in `.agents/vendor-lock.json`.
2. Commit a relative symlink to the sibling source repository.
3. Use a Git submodule for the upstream repository.

## Decision

Commit the released package under `.agents/skills/evolve-software-architecture`. Record the upstream URL, tag, commit SHA, and package path in `.agents/vendor-lock.json`. Use the upstream `scripts/vendor-skill.py --update` flow for updates; it compares the existing copy with its locked commit and refuses to overwrite drift.

## Consequences

Contributors receive a working repository-scoped Skill without a separate setup step. The copy must be deliberately updated and reviewed. The sibling clone remains the only authoring source; the XiLuoLin copy is a release artifact.

## Revisit conditions

Reconsider when the Agent Skills installer can provide a reproducible, project-pinned dependency with equivalent reviewability and no duplicate-trigger ambiguity.
