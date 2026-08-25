# MarkText Scorer Traceability and Profile Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a redacted, hash-addressable record of invalid structured scorer payloads while keeping the v2 schema gate strict and keeping declared Claude/DeepSeek profile data separate from runtime-observed model identifiers.

**Architecture:** Add a small runner helper that writes one diagnostic JSON artifact per rejected score result, keyed by invocation and run ID. The artifact contains the validation error, redacted payload text, payload digest, and redacted runtime metadata; the manifest references the artifact without exposing absolute paths. Existing score validation remains unchanged and invalid samples remain failed. Profile provenance is documented and tested as separate declared, alias, configuration-manager, and observed-model fields.

**Tech Stack:** Python 3 standard library, `unittest`, JSON manifests, existing `run_forward_eval.py` runner, Markdown evaluation documentation.

**Spec:** The delegated handoff from `feat/eval-accuracy-and-doc-drift@0349f6f`: scorer-output calibration and failed-payload traceability only; no Skill, Electron adapter, or `v0.2.0` release changes.

## Global Constraints

- Do not modify `skills/evolve-software-architecture/` or add an Electron adapter.
- Do not rerun producer calls or modify the original AIRI/MarkText result directories.
- Keep the v2 nine-dimension score and strict Accuracy Gate unchanged.
- Store only redacted diagnostic content and relative artifact references; no absolute local paths, credentials, session files, or provider configuration.
- Treat `deepseek-v4-pro` as the declared provider label, `fable` as the CLI alias, and Claude `modelUsage` names as observed runtime identifiers; do not merge these fields.
- Work on the existing `feat/eval-accuracy-and-doc-drift` branch with small Conventional Commit(s).

### Task 1: Define the failure diagnostic contract with a failing test

**Files:**
- Modify: `tests/test_forward_eval.py`
- Modify: `scripts/run_forward_eval.py`

**Interfaces:**
- Produce `write_score_failure_diagnostic(output_dir, result, error, run_id, known_paths) -> dict[str, str]`.
- The returned reference contains only a relative diagnostic `path`, the diagnostic file `sha256`, and the original redacted `payload_sha256`.

- [ ] **Step 1: Write the failing test**

Add a unit test that constructs a failed scorer `RunResult` whose answer contains a temporary checkout path, calls `write_score_failure_diagnostic`, and asserts that:

```python
reference["path"].startswith("diagnostics/score-failures/")
reference["path"].startswith("/") is False
payload = load_json(output / reference["path"])
payload["error"] == "invalid score"
"/Users/timekettle/" not in json.dumps(payload)
"timekettle" not in json.dumps(payload)
payload["payload_sha256"] == sha256(payload["payload_text"].encode()).hexdigest()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_forward_eval.ForwardEvaluationTest.test_score_failure_diagnostic_redacts_and_hashes_payload -v
```

Expected: FAIL because the helper does not yet exist.

- [ ] **Step 3: Implement the minimal diagnostic writer**

Create the helper next to `write_json`. It must write:

```json
{
  "schema_version": 1,
  "id": "score-treatment-r1",
  "phase": "score",
  "variant": "treatment",
  "repetition": 1,
  "attempts": 1,
  "error": "invalid score",
  "payload_sha256": "<sha256 of redacted payload_text>",
  "payload_text": "<redacted exact scorer answer>",
  "metadata": {}
}
```

Use `redact_text` for `error` and `payload_text`, `redact_value` for metadata, and write the file below `output_dir / "diagnostics" / "score-failures"` using a filename containing the invocation ID and `run_id`. Return only relative path and digests.

- [ ] **Step 4: Run the focused test to verify it passes**

Run the same unittest command; expected PASS.

- [ ] **Step 5: Commit the contract and helper**

```bash
git add tests/test_forward_eval.py scripts/run_forward_eval.py docs/superpowers/plans/2026-08-25-marktext-scorer-traceability.md
git commit -m "test(evals): define scorer failure diagnostics"
```

### Task 2: Attach diagnostics to rejected score records

**Files:**
- Modify: `scripts/run_forward_eval.py`
- Modify: `tests/test_forward_eval.py`

**Interfaces:**
- `persist_score` calls the helper only when `validate_score` rejects a structured scorer answer.
- `result.metadata["failure_diagnostic"]` stores the relative reference so `manifest.json` and `prior_failures` point to the committed artifact.

- [ ] **Step 1: Write the failing integration-style test**

Add a test that runs `main` with a mocked six-call score-only fixture where one scorer returns a structurally invalid v2 payload, then asserts:

```python
manifest["results"][...]["success"] is False
manifest["results"][...]["metadata"]["failure_diagnostic"]["path"]
(output / relative_path).is_file()
summary["dataset_complete"] is False
```

The test must also assert that the source answer directory and source manifest bytes remain unchanged.

- [ ] **Step 2: Run the focused test to verify it fails**

Run the new test alone; expected FAIL because rejected scores currently keep only an error string.

- [ ] **Step 3: Wire the helper into `persist_score`**

On `EvaluationError`, retain `result.answer`, set `result.success = False`, write the diagnostic with the current `run_id`, and attach the returned reference to `result.metadata`. Do not turn a rejected score into a successful score and do not change `validate_score` or aggregate thresholds.

- [ ] **Step 4: Run focused and existing tests**

```bash
python3 -m unittest tests.test_forward_eval.ForwardEvaluationTest.test_invalid_score_persists_failure_diagnostic -v
python3 -m unittest discover -s tests -v
```

Expected: the focused test and the complete suite pass.

- [ ] **Step 5: Commit the integration**

```bash
git add scripts/run_forward_eval.py tests/test_forward_eval.py
git commit -m "feat(evals): retain rejected scorer payload diagnostics"
```

### Task 3: Lock profile provenance and documentation

**Files:**
- Modify: `tests/test_forward_eval.py`
- Modify: `evals/README.md`

**Interfaces:**
- No score or case digest changes.
- The profile contract remains: `model` is the declared provider label, `model_argument` is the CLI alias, `configuration_manager` is CCSwitch, and manifest-level `observed_models` comes from Claude `modelUsage`.

- [ ] **Step 1: Add the failing provenance assertion**

Add a deterministic test using the committed Claude manifest fixture that asserts:

```python
profile["runtime"] == "claude-code"
profile["configuration_manager"] == "CCSwitch"
profile["model"] == "deepseek-v4-pro"
profile["model_argument"] == "fable"
set(manifest["observed_models"]) == {"claude-fable-5[1M]", "claude-haiku-4-5"}
```

If a future implementation collapses declared and observed names, this test must fail.

- [ ] **Step 2: Run it and confirm the current implementation’s provenance shape**

Run the focused test. If it passes immediately, treat this as a documented invariant test rather than a production change; do not add redundant profile fields.

- [ ] **Step 3: Clarify the profile wording in `evals/README.md`**

Keep the existing command examples and add one concise statement that the DeepSeek V4 Pro value is user-declared through CCSwitch, while `observed_models` is the runtime-reported Claude model usage. State that profiles with different aliases or observed IDs are not resumable or poolable.

- [ ] **Step 4: Run the full deterministic checks**

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate-skill.py
python3 -m py_compile scripts/run_forward_eval.py scripts/vendor_lib.py scripts/validate-skill.py
git diff --check
```

- [ ] **Step 5: Commit documentation and invariant test**

```bash
git add tests/test_forward_eval.py evals/README.md
git commit -m "docs(evals): clarify Claude model provenance"
```

### Task 4: Validate without spending model quota

**Files:**
- No producer or Skill files modified.
- Verify: existing MarkText result directory remains unchanged except for no new run.

- [ ] **Step 1: Run MarkText dry-run and score-only matrix checks**

```bash
python3 scripts/run_forward_eval.py --case evals/cases/marktext-v0.2.json --runtime claude-code --phases all --dry-run | python3 -c 'import json,sys; assert len(json.load(sys.stdin)) == 30; print("marktext calls: 30")'
python3 scripts/run_forward_eval.py --case evals/cases/marktext-v0.2.json --runtime claude-code --phases score --dry-run | python3 -c 'import json,sys; assert len(json.load(sys.stdin)) == 6; print("score calls: 6")'
```

- [ ] **Step 2: Verify existing result integrity**

Assert that the MarkText manifest still has `planned_calls=30`, `dataset_complete=false`, 18 routing answers, 6 behavior answers, and 3 valid scores; assert no absolute `/Users`, `/home`, or temp paths in committed result files.

- [ ] **Step 3: Do not rerun scorer calls in this change**

The next session may use `--phases score --rescore-from` only after deciding the calibration contract. This change ends with deterministic evidence; it does not change the Skill or release gates.

## Self-review checklist

- [ ] Invalid structured scorer answers remain failed and continue to block dataset completeness.
- [ ] Diagnostic payloads are redacted, relative-path referenced, and hash-addressable.
- [ ] Provider failures without a payload are not misrepresented as structured scorer payloads.
- [ ] DeepSeek declared model, CLI alias, CCSwitch, and observed Claude identifiers remain separate.
- [ ] Existing AIRI and MarkText producer answers and original summaries are not rewritten.
- [ ] No Electron adapter, Skill content, XiLuoLin vendor copy, or `v0.2.0` tag is changed.
