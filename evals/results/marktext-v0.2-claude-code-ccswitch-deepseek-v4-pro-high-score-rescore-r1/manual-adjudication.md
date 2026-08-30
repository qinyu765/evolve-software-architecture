# MarkText v2 scorer calibration — incomplete rescore

- Source: `marktext-v0.2-claude-code-ccswitch-high-full-r3`
- Source manifest SHA-256: `7491ac7da8909abce04895f44ed94eac567a28c63ffb86198bfd5ab115ee7ef0`
- Profile: Claude Code `2.1.233` + CCSwitch, declared model `deepseek-v4-pro`, CLI alias `fable`, `high`
- Contract: `architecture-review-v2.md` + `architecture-review-v2.schema.json`
- Producer answers reused: `6/6`
- New scorer calls: `6`

## Results

- Valid structured scores: `1/6` (`score-treatment-r2`, `18/18`, Accuracy Gate passed)
- Rejected structured payloads: `3/6`
  - `score-control-r1`
  - `score-control-r2`
  - `score-treatment-r1`
- Timeouts at the configured 900-second limit: `2/6`
  - `score-control-r3`
  - `score-treatment-r3`

All three rejected payloads contain exactly one decision-relevant documentation conflict but declare `accuracy.unresolved_decision_conflict_count=0`. The strict validator therefore rejects them with `accuracy unresolved_decision_conflict_count does not match documentation_drift`. Their redacted payloads and hashes are retained under `diagnostics/score-failures/`. Timeout failures have no structured payload and are not represented as payload diagnostics.

## Decision

This rescore confirms that the failure-diagnostic path works and that the scorer-output problem is reproducible, but it does not produce a complete MarkText Treatment score set. The result must remain incomplete evidence. Do not infer a shared AIRI/MarkText Electron-boundary failure, add an Electron adapter, or publish `v0.2.0` from this rescore.

The next calibration should explicitly address the scorer's reconciliation of `decision_relevant` documentation drift and `unresolved_decision_conflict_count`, while keeping the v2 schema and Accuracy Gate strict. Timeout handling should be treated separately from structured-payload validity.
