# Architecture-review v2.1 scorer policy

This policy applies only to evaluations that use the pinned
`architecture-review-v2.1` rubric and schema. It does not select a producer
model, modify the Skill, or authorize a release.

## Scorer roles

- **Default scorer:** Codex GPT-5.6 Luna with `reasoning_effort=max`.
- **Shadow scorer:** DeepSeek V4 Pro through Claude Code and CCSwitch with
  `model_argument=fable` and `reasoning_effort=high`.
- Declared provider model, CLI argument, configuration manager, and
  runtime-reported model identifiers remain separate provenance fields.

The default score is the v2.1 decision input. A shadow score is calibration
evidence only and never replaces the default score automatically.

## Failure handling

- Keep the strict schema and runner validation unchanged.
- Invalid JSON, unknown dimension identifiers, cross-field count mismatches,
  and timeouts remain failed samples.
- Do not normalize a rejected payload or copy a shadow result into a failed
  default cell.
- Resume only an execution-compatible incomplete profile; otherwise create a
  new output directory and retain the earlier attempt as audit evidence.

## Human adjudication

For a high-impact evaluation, manually check every material factual error and
every decision-relevant `conflict` or `unknown` drift entry against the pinned
implementation, configuration, tests, build scripts, and Git history. A valid
structured payload is necessary but is not sufficient evidence of factual
accuracy.

The committed gold fixtures define the current material/minor and
decision-relevance boundaries. Changes to those labels require an explicit
adjudication update rather than silent fixture regeneration.

## Canonical evidence

Original answers, scores, diagnostics, and manifests are immutable. A replay
uses a new result directory. The machine-readable canonical matrix is
`results/architecture-review-v2.1-canonical.json`; directories listed as
`audit_only` remain available for provenance but do not contribute to the
canonical comparison.

## Revisit conditions

Revisit this policy when the default scorer produces a contract rejection,
the scoring contract changes, or the roadmap adds the v0.3 non-UI/SDK case.
Until a separate release decision passes the roadmap promotion gates, this
policy does not justify an Electron adapter or `v0.2.0` release.
