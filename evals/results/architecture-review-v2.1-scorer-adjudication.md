# Architecture-review v2.1 scorer adjudication

Run date: 2026-08-26. This is a calibration and audit artifact. It does not
rewrite any score payload, manifest, producer answer, or historical v2 result.

## Scope and method

The adjudication covers the four original v2.1 producer/all runs, the four
original score-only cross cells, and the two clean DeepSeek replay cells. All
comparisons use the v2.1 rubric/schema and the pinned repository commits:

- rubric SHA-256: `64489b2290d24f0ae95fdabe14abcf34a4edbf6f7dcc044a65ed3034ec3c3b4e`
- schema SHA-256: `e5609858147c7005cf786d059abe4d402d48271ed45f6701ee1a9c519bf3c8a6`
- AIRI: `5228f94123e42416435e7f7e8215df26f3bb065b`
- MarkText: `e52106fd1cdcbd33c1258b7b0cdc7013c4c5d86c`

“Confirmed” below means the repository evidence supports the scorer's
gate-driving conclusion. “Severity caveat” means the underlying discrepancy
is real, but the material/minor boundary or the product inference needs care.
The review manually adjudicates every material finding and every
decision-relevant conflict; generated minor-error counts are left unchanged.

## Matrix-level result

The totals column lists the six valid `total` values in control-then-treatment
order. The MarkText and AIRI DeepSeek scores for Codex-produced answers use
the clean replay, because the first DeepSeek cross cells contained preserved
contract rejects.

| Producer answers | Scorer | Valid | Totals | Accuracy gates | Adjudication |
|---|---|---:|---|---:|---|
| AIRI DeepSeek | DeepSeek native | 6/6 | 17,18,18 / 18,18,18 | 6/6 pass | Baseline, but too lenient on current-fact errors |
| AIRI DeepSeek | Codex cross | 6/6 | 16,15,16 / 17,16,17 | 0/6 pass | More reliable on the material current-state checks |
| AIRI Codex | Codex native | 6/6 | 18,17,16 / 18,17,17 | 5/6 pass | Correctly catches the capability-lifecycle overstatement |
| AIRI Codex | DeepSeek clean replay | 6/6 | 18,18,18 / 18,18,18 | 6/6 pass | Contract-stable, but misses that material issue |
| MarkText DeepSeek | DeepSeek native | 6/6 | 18,18,18 / 18,18,18 | 6/6 pass | Too lenient on alias, engine, and focus-mode facts |
| MarkText DeepSeek | Codex cross | 6/6 | 15,17,14 / 18,16,17 | 2/6 pass | More reliable on concrete implementation checks |
| MarkText Codex | Codex native | 6/6 | 18,18,17 / 18,17,18 | 4/6 pass | Correctly treats the unqualified PG14 claim as material + unresolved |
| MarkText Codex | DeepSeek clean replay | 6/6 | 18,18,18 / 17,18,18 | 6/6 pass | Notices some drift, but undercounts its decision relevance |

The first DeepSeek cross-runtime runs were incomplete: AIRI was `5/6` and
MarkText `4/6`, with three identical `unknown dimension` contract rejects and
no timeouts. The clean replays were `6/6` with no rejects or timeouts. The
failure pattern is therefore output-format instability, not evidence that the
strict validator should be relaxed.

## Item-level adjudication

### AIRI DeepSeek producer, Codex scorer

All seven material findings in the Codex cross cell were checked against the
pinned AIRI tree.

| Sample | Finding | Verdict |
|---|---|---|
| control-r1 | Main-window background residency was described as macOS-only. | **Confirmed material.** `windows/main/index.ts:153-160` hides the main window on close on every platform; `main/index.ts:291-297` separately controls quit-after-all-windows. The answer conflated the two behaviours. |
| control-r2 | All six services and five plugins were described as independent processes using `server-sdk`/server-channel. | **Confirmed material.** The tree mixes in-process services, server-sdk consumers, MCP stdio, Godot sidecar, and other transports. The common-topology claim changes the boundary recommendation. |
| control-r3 | There was said to be no window manager abstraction beyond `createReusableWindow`. | **Confirmed material.** `windows/shared/referenced-window.ts:21-99` provides a keyed `ReferencedWindowManager` backed by a `Map`. It is narrow, not a universal registry, but the absolute statement is false. |
| control-r3 | Server-channel, HTTP, MCP, and Godot were said to share one `appHooks.onStart/onStop + mutex` lifecycle. | **Confirmed material.** The integrations use different lifecycle hooks and cleanup paths; they are not one already-unified contract. |
| treatment-r1 | There was said to be no evidence for a second independent client. | **Confirmed contradiction; severity caveat.** The answer itself cites LAN QR pairing and multiple server consumers, so “no evidence” is too strong. Those consumers still do not by themselves prove a product requirement for a second independent client. |
| treatment-r2 | `node-worker` was proposed as an out-of-process, restricted security slice. | **Confirmed material.** The current node runtime maps this direction to an unimplemented transport; a `worker_threads` design would not be an OS process or sandbox and would retain host privileges. |
| treatment-r3 | Duplicated Eventa/plugin snapshot/debug types were treated as the public third-party plugin contract and re-export migration target. | **Confirmed material.** The answer confused host-internal/application snapshot types with the stable plugin-protocol boundary, so its first migration step targets the wrong contract. |

The native DeepSeek scorer reported zero material errors for this producer.
The repository checks above make that an evaluator false negative rather than
evidence that the producer answer was fully accurate.

### MarkText DeepSeek producer, Codex scorer

The five material findings in the Codex cross cell are supported.

| Sample | Finding | Verdict |
|---|---|---|
| control-r1 | `main_renderer/*` was called unused dead code and safe to delete. | **Confirmed material.** `packages/desktop/vitest.config.ts:14-21` actively maps the alias for the unit-test surface; deletion requires coordinated test/config migration. |
| control-r2 | `markdownToHtml`/`getImageInfo` were treated as pure functions at a stable `.d.ts` seam. | **Confirmed material.** The relevant markdown/export path depends on DOM, sanitization, Mermaid/image handling, and engine-side state; the proposed boundary is not a pure-function contract as stated. |
| control-r3 | Focus mode was called a no-op and deferred. | **Confirmed material + unresolved conflict.** `packages/muya/src/muya.ts:372-379` toggles the focus class and option, and the render path applies the class at `:1696-1699`; the implementation/test evidence contradicts the stale no-op framing. |
| treatment-r2 | The checkout was said to contain only a clone record and no usable Git history. | **Confirmed material for this task.** The pinned checkout has inspectable history (`2143` reachable commits); the answer therefore did not perform the requested historical verification. |
| treatment-r2 | Adding a window type was reduced to `WindowType`, a `BaseWindow` subclass, and an `App` method. | **Confirmed material.** Renderer routing/bootstrap, window registration, and related behaviour tests are also part of the change surface. |

The native DeepSeek scorer reported all six MarkText DeepSeek answers as
accuracy-gate passing. That result is not supported by these direct checks;
Codex is the more dependable scorer for this producer.

### AIRI Codex producer

The Codex native scorer reported one material error and one unresolved
decision-relevant conflict in `treatment-r2`; the DeepSeek replay reported a
clean accuracy gate. The Codex finding is **confirmed**.

The answer treated the host's four `ExtensionSession.phase` values
(`setting-up/ready/failed/stopped`) as if they were the whole capability
boundary, and deferred the richer lifecycle. The pinned tree already has a
capability registry/state path with `announced/ready/degraded/withdrawn`
states, wait primitives, IPC exposure, and tests. The four session states and
the capability states are different layers. This affects the recommendation
to defer the abstraction, so the material error and unresolved conflict are
appropriate.

The DeepSeek replay's six valid payloads are useful as a stability signal, but
its all-pass gate is a false negative for this item. Other differences in this
pair are minor citation or evaluator-judgment differences, not contract
failures.

### MarkText Codex producer

The Codex native scorer reported a material error plus an unresolved conflict
for `treatment-r2`, and an unresolved conflict for `control-r1`. The material
finding is **confirmed**.

`packages/desktop/test/PARITY_SCOREBOARD.md` still says PG14 is the only
remaining `test.fail()` gap, while
`packages/desktop/test/e2e/parity-source-undo-saved.spec.ts` is marked FIXED
and uses a normal test; the current editor implementation calls
`replaceContent` for that boundary. This is a real documentation/implementation
conflict. The producer answer only cites the stale scoreboard as current and
does not reconcile it with the fixed test, implementation, and history, so the
Codex scorer is correct to make it material and decision-relevant.

The DeepSeek replay also noticed the PG14 drift in some payloads, but marked it
non-decision-relevant and therefore allowed the accuracy gate to pass. Under
v2.1, a parity scoreboard used to choose migration scope and test gates is
decision-relevant; this is an undercount by the DeepSeek scorer, not a contract
problem.

## Scorer decision

### Contract and routing stability

- Codex scorer: `24/24` valid payloads across the four original matrix cells,
  zero contract rejects, zero timeouts.
- DeepSeek scorer: native DeepSeek cells were valid; the first cross-runtime
  cells were `9/12` valid because three payloads used rubric labels
  (`Evidence`/`Verification`) instead of schema identifiers
  (`evidence`/`verification`). Clean AIRI and MarkText replays were `12/12`
  valid, with zero timeouts.
- `model`, `model_argument`, `configuration_manager`, and
  `observed_models` remain separate audit fields. The DeepSeek profile is
  `model=deepseek-v4-pro`, `model_argument=fable`, `configuration_manager=CCSwitch`;
  runtime observations remain `claude-fable-5[1M]` and
  `claude-haiku-4-5`.

### Provisional recommendation

Use Codex GPT-5.6 Luna/max as the v2.1 default scorer candidate and keep
DeepSeek V4 Pro as a shadow/calibration scorer. Keep the strict validator and
the v2.1 cross-field formula unchanged. For high-impact evaluations, manually
audit material errors and decision-relevant documentation conflicts against
implementation, tests, and history; a valid JSON payload is not by itself an
accuracy guarantee.

This recommendation is provisional. This calibration does not modify the
Skill, add an Electron adapter, rewrite any result, or publish `v0.2.0`.

## Source artifacts

- Matrix summary: `architecture-review-v2.1-matrix-summary.md`
- DeepSeek replay summary: `architecture-review-v2.1-scorer-replay-r2-summary.md`
- Clean AIRI replay: `airi-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-replay-r2`
- Clean MarkText replay: `marktext-v0.2-producer-codex-scorer-deepseek-v4-pro-high-v2.1-replay-r3`
- Original eight matrix cells: the eight directories listed in the matrix summary
