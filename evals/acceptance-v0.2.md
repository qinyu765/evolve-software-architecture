# Generic v0.2 acceptance

This protocol checks usable observable behavior, not a statistical improvement over a base model. It supersedes the historical desktop experiment only as the v0.2 release gate. Old cases, scores, scorer policy, and failed attempts remain unchanged.

## Fixed tasks and isolation

`cases/generic-v0.2.json` pins AIRI and Click 8.1.8 and the exact user tasks. Run six behavior tasks and six routing tasks once with one Codex configuration. AIRI retains its existing companion Skills. Click has none; its tasks distinguish absent authorization from explicit permission for the maintainer's version-pinned `docs/`. The conflict task uses a user constraint against an actual installed Vue Skill preference, not a fabricated official Skill.

Each task runs in a fresh temporary checkout with the candidate package materialized from a fixed commit. Only the temporary entrypoint receives the historical routing marker; frontmatter stays unchanged. Producers get the user request and raw repository, without an expected architecture. Use ephemeral, read-only executions, ignore user configuration and execution rules, and preserve the effective model, effort, CLI version, OS, timeout, and content digests in the manifest. Model errors/timeouts stay failed attempts; do not silently retry or overwrite a result directory.

Source checkouts and active project copies are never changed. Temporary instrumentation and runtime logs stay outside the repository. Published answers, review outcomes, and compact read-command traces are redacted for local paths. Companion inventories include descriptions, declared provenance, and content digests; observed reads distinguish actual use from mere installation. Because AIRI retains multiple existing Skills, the test validates selection in that environment rather than a controlled one-companion-only comparison.

## Observable acceptance criteria

- All three architecture/refactoring/major-requirement routing tasks load the Skill; the rename, styling, and dependency-update tasks do not.
- AIRI review and requirement tasks ground relevant runtime/state/trust boundaries in current implementation, use applicable companion guidance, and do not substitute a Tauri topology.
- Click review and requirement tasks ground public APIs, compatibility, consumers, and tests in the pinned implementation and maintainer documentation; they do not impose desktop/UI structure.
- Requirement reviews discover already-implemented capabilities before proposing abstractions; compare viable options and give ownership/interface effects, trade-offs, incremental migration, rollback, and concrete verification.
- Missing companion coverage without fallback authorization causes a specific question offering documentation, supplying a Skill, or narrowing scope; technology-dependent conclusions stop. With authorization already supplied, the answer continues without asking again.
- Conflicting companion preferences are explained against user/repository constraints without a forced rewrite, unauthorized edits, or falsely labeling community guidance official.
- Decision-driving current-state claims have no independently confirmed material factual error. Consequential unknowns remain conditional or become explicit questions rather than invented facts.

An independent fresh reviewer receives the task, package policy, raw answer, and pinned repository, and checks the applicable criteria against source/configuration/tests/history. It reports material errors, consequential unresolved questions, and an explicit pass/fail. No proposed target architecture or producer rationale is supplied by the maintainer. Human verification checks disputed/material findings and important claims; raw reviewer output remains unchanged if a separate adjudication is needed.

## Running and finishing

```bash
python3 scripts/run_acceptance.py --phase answers \
  --airi-source ../airi --click-source /path/to/click \
  --skill-ref <fixed-candidate-commit> --model <available-codex-model> \
  --output-dir evals/results/generic-v0.2-<profile>-answers-r1
python3 scripts/run_acceptance.py --phase reviews \
  --airi-source ../airi --click-source /path/to/click \
  --skill-ref <same-candidate-commit> --model <same-codex-model> \
  --answers-from evals/results/generic-v0.2-<profile>-answers-r1 \
  --output-dir evals/results/generic-v0.2-<profile>-reviews-r1
```

The default effort is `high`, concurrency is 3, and hard per-call timeout is 900 seconds. The runner records readiness evidence rather than calculating a score or authorizing a release. Review only behavior samples; routing is checked through markers and read traces. After an evidenced Skill correction, rerun only affected tasks in a new directory and retain the failed attempt. Any changed task or execution profile must be recorded explicitly; never count infrastructure failures as model behavior passes.

Release also requires package validation, existing tests, byte-identical archive checks, and reproducible old/candidate release packaging. Verify the released package tree matches the accepted candidate, publish v0.2.0 upstream, then update project copies only if separately requested.

## Result index

Results and independent adjudication will be linked here after the fixed candidate has completed acceptance. A missing or incomplete result does not satisfy the release gate.
