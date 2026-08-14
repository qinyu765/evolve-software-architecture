# Evolve Software Architecture

An agent Skill for evidence-based software architecture guidance.

It helps an agent understand a repository before recommending structural change, choose quality attributes deliberately, compare viable options, and produce an incremental migration path. It is intentionally project-aware: Desktop/Tauri guidance is an adapter, not a default model for SDKs, Web, CLI, Mobile, Data, or AI projects.

## What it does

Use it when a decision affects module boundaries, process boundaries, extensibility, long-term maintainability, technical-debt direction, or cross-cutting design. It produces an architecture review with evidence, current friction, quality-attribute trade-offs, options, a recommendation, migration steps, and verification criteria.

It is not a promise of a final architecture. The goal is to reduce future change cost while keeping uncertain decisions reversible.

## Install

For Codex and other Agent Skills-compatible tools:

```bash
npx skills@latest add qinyu765/evolve-software-architecture \
  --skill evolve-software-architecture --agent codex --copy --yes
```

This installs the current public source into `.agents/skills` and writes the ecosystem `skills-lock.json`. For a release-pinned project copy such as XiLuoLin, clone this repository and run `python3 scripts/vendor-skill.py --target <repo> --ref <release-tag>`; the custom `.agents/vendor-lock.json` records the exact tag and peeled commit. Do not install both a project copy and a user-level copy of the same Skill in the same working context.

## Repository layout

- `skills/evolve-software-architecture/` — the installable Skill.
- `evals/` — trigger, quality, and cross-project evaluation cases.
- `ROADMAP.md` — capability phases and promotion gates.
- `docs/adr/` — decisions about the Skill itself.
- `scripts/` — validation and controlled vendor synchronization.

## Development

```bash
python3 scripts/validate-skill.py
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/evolve-software-architecture/scripts/collect_repo_signals.py
python3 skills/evolve-software-architecture/scripts/collect_repo_signals.py --repo .
```

The Skill's runtime instructions are deliberately concise. Detailed domain guidance belongs in one-level-deep references so only the relevant project adapter is loaded.

## Design principles

- repository facts precede architecture opinions;
- facts, inferences, unknowns, and constraints stay distinct;
- quality attributes are ranked and traded off;
- the current design remains an option;
- migrations are incremental, observable, and reversible;
- XiLuoLin is the first evaluation case, not a hidden default;
- lessons enter the core only after surviving materially different project types.

## License

Apache-2.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for adapted ideas and source notices.
