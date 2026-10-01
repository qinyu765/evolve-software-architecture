# Evolve Software Architecture

An agent Skill for evidence-based software architecture guidance.

It helps an agent understand a repository before recommending structural change, choose quality attributes deliberately, compare viable options, and produce an incremental migration path. The architecture method is generic; applicable technology Skills supply platform constraints rather than built-in framework adapters.

## What it does

Use it for existing-repository architecture reviews, structural refactoring, or substantial new requirements affecting ownership, boundaries, compatibility, or extensibility. It produces evidence, trade-offs, alternatives, a recommendation, and a migration/verification plan at the task's scale. It changes code only when the user requests implementation; ordinary local work and a separate greenfield-design workflow are outside its trigger.

It is not a promise of a final architecture. The goal is to reduce future change cost while keeping uncertain decisions reversible.

## Technology Skills

The Skill selects installed, accessible guidance relevant to the project's technologies and versions. It prefers verified maintainer-published Skills, then credible community Skills with inspectable provenance, and reports material source/version gaps. It does not treat a Skill's preferred pattern as a fact about the repository.

If suitable guidance is missing, it asks you whether to use official documentation, supply a Skill, or narrow the analysis. It honors permission already given for that task and never installs Skills automatically. For example: “Review this repository's API evolution; use its installed technology Skills, and if none fits, I authorize version-appropriate official documentation.”

## Install

For Codex and other Agent Skills-compatible tools:

```bash
npx skills@latest add qinyu765/evolve-software-architecture \
  --skill evolve-software-architecture --agent codex --copy --yes
```

This installs the current public source into `.agents/skills` and writes the ecosystem `skills-lock.json`. For a release-pinned project copy such as XiLuoLin, clone this repository and run `python3 scripts/vendor-skill.py --target <repo> --ref <release-tag>`; the custom `.agents/vendor-lock.json` records the exact tag and peeled commit. Do not install both a project copy and a user-level copy of the same Skill in the same working context.

## Repository layout

- `skills/evolve-software-architecture/` — the installable Skill.
- `evals/` — compact v0.2 acceptance and immutable historical desktop experiments.
- `ROADMAP.md` — capability phases and promotion gates.
- `docs/adr/` — decisions about the Skill itself.
- `docs/archive/` — unchanged v0.1.2 adapter references, excluded from installation.
- `scripts/` — validation and controlled vendor synchronization.

## Development

```bash
python3 scripts/validate-skill.py
python3 -m unittest discover -s tests -v
python3 scripts/run_forward_eval.py --dry-run
python3 -m py_compile skills/evolve-software-architecture/scripts/collect_repo_signals.py
python3 skills/evolve-software-architecture/scripts/collect_repo_signals.py --repo .
```

The Skill's runtime instructions are deliberately concise. Optional references deepen evidence, trade-offs, decisions, and cooperation with technology Skills. See [v0.2 acceptance](evals/acceptance-v0.2.md) for real-repository tasks and release evidence. The historical forward-evaluation dry run above does not measure v0.2 release readiness.

## Design principles

- repository facts precede architecture opinions;
- facts, inferences, unknowns, and constraints stay distinct;
- quality attributes are ranked and traded off;
- the current design remains an option;
- migrations are incremental, observable, and reversible;
- XiLuoLin is the first evaluation case, not a hidden default;
- lessons enter the core only after surviving materially different project types.

## Releases and maintenance

v0.2.0 replaces built-in adapters with companion Skill cooperation and adds substantial-requirement analysis. Package names, implicit invocation, and vendor-lock format are retained; old pinned releases remain reproducible. This release is validated for observable cross-type behavior, not universal measured improvement over base models. Framework-specific updates belong to companion guidance; core updates follow reproduced failures. Project copies are updated explicitly after an upstream release.

## License

Apache-2.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for adapted ideas and source notices.
