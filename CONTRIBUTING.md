# Contributing

Keep changes focused on the architecture Skill and its evidence. A useful contribution includes the scenario that exposed a gap, the project type involved, the expected behaviour, and the verification used.

## Adding guidance

1. Add a positive or negative evaluation case first.
2. Put repository-specific knowledge in that case. Technology guidance belongs to companion Skills or user-authorized official documentation, not new built-in adapters.
3. Promote a rule into `references/core/` only when it survives the promotion gate in `ROADMAP.md`; prefer a targeted correction to a growing universal checklist.
4. Keep `SKILL.md` concise and under 500 lines; put substantial optional detail in references.
5. Run validation and the representative evaluation commands before opening a pull request.

## Pull requests

Use a focused branch and a Conventional Commit. Explain the evidence, affected project types, trigger implications, and whether the change alters the output contract or vendor synchronization.

For v0.2 behavior changes, use the compact protocol in `evals/acceptance-v0.2.md`. Preserve historical desktop results and scorer policy unchanged. Record independent verification and any limits; do not claim quantitative improvement from a one-run acceptance pass.
