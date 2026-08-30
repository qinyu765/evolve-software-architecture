# Architecture-review v2.1 DeepSeek scorer replay

Run date: 2026-08-26. This replay reused only the six successful Codex producer behavior answers for each case. It used the same v2.1 rubric/schema, pinned repository commits, DeepSeek V4 Pro via Claude Code/CCSwitch (`model_argument=fable`, `reasoning=high`), `call_timeout_seconds=1800`, `max_concurrency=3`, and `repetitions=3`. Each replay has an independent output directory.

AIRI uses replay-r2. The first MarkText replay-r2 was interrupted and resumed while the original process may still have been finishing; although its final manifest was complete, it is retained only as an execution audit. MarkText replay-r3 is the clean, non-overlapping result used below.

The v2.1 contract remained unchanged:

```text
accuracy.unresolved_decision_conflict_count =
  count(documentation_drift where decision_relevant == true and state in {"conflict", "unknown"})

accuracy.gate_pass =
  material_error_count == 0 and unresolved_decision_conflict_count == 0
```

## Replay results

| Case | Producer answers | Valid / planned | Timeout | Contract rejects | Accuracy gate | Dataset complete | Control totals | Treatment totals | Control M/m/U | Treatment M/m/U |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| AIRI | Codex GPT-5.6 Luna/max | 6 / 6 | 0 | 0 | pass | yes | 18, 18, 18 | 18, 18, 18 | 0 / 0 / 0 | 0 / 4 / 0 |
| MarkText | Codex GPT-5.6 Luna/max | 6 / 6 | 0 | 0 | pass | yes | 18, 18, 18 | 17, 18, 18 | 0 / 1 / 0 | 0 / 2 / 0 |

`M/m/U` means summed material, minor, and unresolved-decision-conflict counts across the valid payloads. Invalid JSON rejects: 0. Timeout rejects: 0.

## Comparison with the first DeepSeek cross-runtime score

| Case | First cross-runtime score | Replay | Interpretation |
| --- | --- | --- | --- |
| AIRI | 5 / 6 valid; 1 `unknown dimension` contract reject | 6 / 6 valid; 0 rejects | The format failure did not reproduce; scorer judgment also varied on minor factual findings. |
| MarkText | 4 / 6 valid; 2 `unknown dimension` contract rejects | 6 / 6 valid; 0 rejects | The format failure did not reproduce; scorer judgment also varied on dimensions and factual findings. |

All three first-run invalid payloads used rubric display labels in `factual_errors[].affected_dimensions` (`Evidence` and/or `Verification`) instead of the schema/runner identifiers `evidence` and `verification`. Offline validation confirmed that replacing only those labels would make the payloads valid, but no recorded result was repaired. The replay generated valid payloads directly, so the strict validator remains appropriate and the observed failure is output-format instability rather than a validator defect.

## Decision

The replay strengthens the provisional scorer recommendation:

- Keep Codex GPT-5.6 Luna/max as the v2.1 default scorer candidate: it produced valid payloads in all four original matrix cells.
- Keep DeepSeek V4 Pro as a shadow/calibration scorer: it produced valid payloads in both replay cells, but the first cross-runtime run had 3 rejects out of 12 attempted cross scores and the valid runs show evaluator-judgment variation.
- Do not modify the Skill, relax the validator, add an Electron adapter, or publish `v0.2.0` based on this replay alone.

## Provenance

- AIRI replay output: `airi-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-replay-r2`
  - source: `airi-v0.2-codex-gpt-5.6-luna-max-full-v2.1-r1`
  - run ID: `842b418ae7254669acecd84d11532a3f`
  - manifest SHA-256: `2a9af2d1220bfe1f332534c70072f6e8bdaa86d96a6989c6f8aa1523308ff296`
- MarkText replay output: `marktext-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-replay-r2`
  - superseded execution audit only; not used for the clean result table
- MarkText clean replay output: `marktext-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-replay-r3`
  - source: `marktext-v0.2-codex-gpt-5.6-luna-max-full-v2.1-r1`
  - run ID: `ceae2bd82d63428087cac3e166dc5c92`
  - manifest SHA-256: `fbfdbe892f3c580969a339d6f83a4c28867b1f33159639e901eba18baa45e2e4`
- AIRI repository commit: `5228f94123e42416435e7f7e8215df26f3bb065b`.
- MarkText repository commit: `e52106fd1cdcbd33c1258b7b0cdc7013c4c5d86c`.
- DeepSeek runtime `observed_models`: `claude-fable-5[1M]`, `claude-haiku-4-5`; these remain separate from `model` and `model_argument`.
