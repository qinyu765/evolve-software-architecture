# Architecture review rubric

Score each dimension from 0 to 2:

- **0** — missing or contradicted by repository evidence.
- **1** — present but incomplete or weakly grounded.
- **2** — explicit, evidence-backed, and actionable.

| Dimension | Full-credit signal |
| --- | --- |
| Scope and classification | The repository type and confidence are stated from multiple signals. |
| Evidence | Claims cite paths, symbols, commands, history, or user input. |
| Current friction | The review explains where a change spreads and why it matters. |
| Quality attributes | A small ranked set has explicit trade-offs and verification. |
| Options | At least two viable options, including current shape when reasonable. |
| Recommendation | One direction follows from the stated drivers and evidence. |
| Migration | Steps are incremental, observable, and reversible. |
| Verification | Tests, measurements, failure modes, and completion criteria are concrete. |
| Generalization | Project-specific facts are not smuggled into core rules. |

A review is ready for a user decision at 14/18 or higher and with no zero in Evidence, Options, Recommendation, or Migration. A score is a diagnostic aid, not a substitute for user judgment.
