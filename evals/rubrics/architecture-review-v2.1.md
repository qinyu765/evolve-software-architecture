# Architecture review rubric v2.1

Score each of the nine dimensions from 0 to 2. `total` is exactly their sum and remains capped at 18; accuracy is a separate gate, not a tenth dimension.

| Dimension | Full-credit signal |
| --- | --- |
| Scope and classification | The repository type and confidence are stated from multiple signals. |
| Evidence | Claims cite paths, symbols, commands, history, or user input and distinguish current evidence from intent. |
| Current friction | The review explains where a change spreads and why it matters. |
| Quality attributes | A small ranked set has explicit trade-offs and verification. |
| Options | At least two viable options, including current shape when reasonable. |
| Recommendation | One direction follows from the stated drivers and verified evidence. |
| Migration | Steps are incremental, observable, and reversible. |
| Verification | Tests, measurements, failure modes, and completion criteria are concrete. |
| Generalization | Project-specific facts are not smuggled into core rules. |

## Evidence and documentation drift

For every material claim, inspect the source appropriate to that claim. Current runtime behavior normally needs implementation, configuration, tests, build scripts, or recent history; ADRs and documentation express intent or historical context unless current evidence confirms them. Do not use an absolute source precedence when the repository has generated code, migrations, or multiple runtime paths.

When documentation and implementation disagree:

- record the documentation claim and the implementation evidence;
- classify the state as historical, conflict, unknown, or resolved;
- mark whether the conflict changes the recommendation;
- treat an explicit, evidence-backed uncertainty as preferable to an invented answer;
- report a material factual error when the answer presents stale documentation as current and relies on it for a decision.

## Accuracy gate and v2.1 cross-field contract

`accuracy.gate_pass` is true only when the answer has zero material factual errors and zero unresolved decision-relevant conflicts. Minor errors remain visible but do not block the gate. The gate is required for Treatment scores; Control accuracy is diagnostic for the counterfactual baseline.

The scorer must compute these fields consistently:

```text
accuracy.unresolved_decision_conflict_count =
  count of documentation_drift entries where
  decision_relevant == true and state in {"conflict", "unknown"}

accuracy.gate_pass =
  material_error_count == 0 and
  unresolved_decision_conflict_count == 0
```

Count each matching drift entry once. Do not count `historical`, `resolved`, or `decision_relevant == false` entries. Do not silently repair a mismatch between the reported count, the drift entries, and the gate; such a payload is invalid and must be rejected by the runner.

A review is ready for a user decision at 14/18 or higher, with no zero in Evidence, Options, Recommendation, or Migration, and with the Treatment accuracy gate passing. A score is a diagnostic aid, not a substitute for user judgment.
