# Architecture-review v2.1 scorer matrix

Run date: 2026-08-25. The four fresh producer/all runs used 30 planned calls each; the four score-only cross cells used 6 planned calls each. Every run used `call_timeout_seconds=1800`, `max_concurrency=3`, `repetitions=3`, and the same v2.1 contract.

The v2.1 contract is pinned by:

- `architecture-review-v2.1.md`: rubric SHA-256 `64489b2290d24f0ae95fdabe14abcf34a4edbf6f7dcc044a65ed3034ec3c3b4e`
- `architecture-review-v2.1.schema.json`: schema SHA-256 `e5609858147c7005cf786d059abe4d402d48271ed45f6701ee1a9c519bf3c8a6`
- `accuracy.unresolved_decision_conflict_count = count(documentation_drift where decision_relevant == true and state in {"conflict", "unknown"})`
- `accuracy.gate_pass = (material_error_count == 0 and unresolved_decision_conflict_count == 0)`

`valid/6` counts only structured payloads accepted by the runner. `M/m/U` below are summed material/minor/unresolved counts across valid payloads for the corresponding variant; incomplete cells therefore summarize only the valid subset.

## Cell completeness and contract stability

| Cell | Producer → scorer | Valid / planned | Timeout | Contract rejects | Accuracy gate | Dataset complete |
| --- | --- | ---: | ---: | ---: | --- | --- |
| AIRI DS→DS | DeepSeek → DeepSeek | 6 / 6 | 0 | 0 | pass | yes |
| AIRI DS→Codex | DeepSeek → Codex | 6 / 6 | 0 | 0 | fail | yes |
| AIRI Codex→DS | Codex → DeepSeek | 5 / 6 | 0 | 1 | pass* | no |
| AIRI Codex→Codex | Codex → Codex | 6 / 6 | 0 | 0 | fail | yes |
| MarkText DS→DS | DeepSeek → DeepSeek | 6 / 6 | 0 | 0 | pass | yes |
| MarkText DS→Codex | DeepSeek → Codex | 6 / 6 | 0 | 0 | fail | yes |
| MarkText Codex→DS | Codex → DeepSeek | 4 / 6 | 0 | 2 | pass* | no |
| MarkText Codex→Codex | Codex → Codex | 6 / 6 | 0 | 0 | fail | yes |

`*` The valid subset passed the reported Treatment accuracy gate; the cell itself is incomplete and must not be treated as a successful score set.

All three DeepSeek scorer contract rejects had the same preserved validator error: `scorer factual error references an unknown dimension`.

- AIRI Codex→DeepSeek: `score-control-r1`.
- MarkText Codex→DeepSeek: `score-control-r1` and `score-treatment-r2`.
- Invalid JSON rejects: 0. Timeout rejects: 0.

## Score distributions and factual findings

| Cell | Control totals | Treatment totals | Control M/m/U | Treatment M/m/U |
| --- | --- | --- | --- | --- |
| AIRI DS→DS | 17, 18, 18 | 18, 18, 18 | 0 / 7 / 0 | 0 / 5 / 0 |
| AIRI DS→Codex | 16, 15, 16 | 17, 16, 17 | 4 / 10 / 0 | 3 / 14 / 0 |
| AIRI Codex→DS | 18, 18 | 18, 18, 18 | 0 / 2 / 0 | 0 / 2 / 0 |
| AIRI Codex→Codex | 18, 17, 16 | 18, 17, 17 | 0 / 2 / 0 | 1 / 4 / 1 |
| MarkText DS→DS | 18, 18, 18 | 18, 18, 18 | 0 / 8 / 0 | 0 / 8 / 0 |
| MarkText DS→Codex | 15, 17, 14 | 18, 16, 17 | 3 / 15 / 1 | 2 / 13 / 0 |
| MarkText Codex→DS | 17, 18 | 18, 18 | 0 / 1 / 0 | 0 / 0 / 0 |
| MarkText Codex→Codex | 18, 18, 17 | 18, 17, 18 | 0 / 2 / 1 | 1 / 0 / 1 |

## Provenance

- DeepSeek producer/scorer profile: `runtime=claude-code`, `model=deepseek-v4-pro`, `model_argument=fable`, `configuration_manager=CCSwitch`, `reasoning=high`. Runtime `observed_models` were recorded separately as `claude-fable-5[1M]` and `claude-haiku-4-5`.
- Codex producer/scorer profile: `runtime=codex`, `model=gpt-5.6-luna`, `model_argument=gpt-5.6-luna`, `reasoning=max`. No runtime-reported `observed_models` were recorded for these runs.
- AIRI repository commit: `5228f94123e42416435e7f7e8215df26f3bb065b`.
- MarkText repository commit: `e52106fd1cdcbd33c1258b7b0cdc7013c4c5d86c`.
- Score-only manifests retain `rescore_source`, source manifest SHA-256, producer run ID, producer profile, scorer profile, source result IDs, and the v2.1 contract digest. Source manifests and source answers were not rewritten.

## Interpretation

- The runner correctly kept DeepSeek cross-runtime contract failures as failures; it did not repair the payload or convert it into a score.
- For the same DeepSeek producer, both native DeepSeek and Codex rescore cells were structurally complete but differed materially in factual judgments and accuracy gates. This is evaluator judgment difference, not a contract failure.
- For the Codex producers, Codex scorer cells were complete and had no contract rejects, while both DeepSeek scorer cross cells were incomplete with the same unknown-dimension rejection pattern. This is a scorer-model/routing stability signal that should not be merged with valid score differences.
- The Codex scorer produced valid payloads for all four producer/scorer cells. Differences among those valid cells should be interpreted as producer-answer quality plus evaluator judgment, using the producer/scorer profiles separately.
- No call reached the 1800-second timeout. The observed stability issue in this run is structured-contract rejection, not timeout.
- This run does not change the Skill, add an Electron adapter, select a new default scorer, or publish `v0.2.0`.

## Result directories

The eight independent manifests and their summaries are in these sibling directories:

- AIRI DS→DS: `airi-v0.2-claude-code-ccswitch-deepseek-v4-pro-high-full-v2.1-r1`
- AIRI DS→Codex: `airi-v0.2-producer-deepseek-scorer-codex-gpt-5.6-luna-v2.1-r1`
- AIRI Codex→DS: `airi-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-r1`
- AIRI Codex→Codex: `airi-v0.2-codex-gpt-5.6-luna-max-full-v2.1-r1`
- MarkText DS→DS: `marktext-v0.2-claude-code-ccswitch-deepseek-v4-pro-high-full-v2.1-r1`
- MarkText DS→Codex: `marktext-v0.2-producer-deepseek-scorer-codex-gpt-5.6-luna-v2.1-r1`
- MarkText Codex→DS: `marktext-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-r1`
- MarkText Codex→Codex: `marktext-v0.2-codex-gpt-5.6-luna-max-full-v2.1-r1`

The two incomplete cells intentionally retain their failure diagnostics and are not marked dataset-complete.
