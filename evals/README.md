# Evaluation status

The v0.1 XiLuoLin case remains the first vertical reference. The machine-readable `cases/airi-v0.2.json` definition is the single source of truth for the independent second-desktop routing and behavior baseline.

The v2 rubric keeps the nine dimensions and an 18-point total, then adds an independent accuracy gate. Its scorer records claim-level evidence and documentation drift; documentation is treated as intent or historical context until implementation, configuration, tests, or history confirm it. A material factual error or unresolved decision-relevant documentation conflict blocks a Treatment result. Control errors remain diagnostic.

Run deterministic checks and inspect the 30-call plan without contacting a model:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_forward_eval.py --dry-run
```

The runner accepts `--repository-source` for any pinned Git repository; `--airi-source` remains a compatibility alias. Contract files can be selected explicitly with `--rubric PATH --schema PATH`. A score-only run requires `--phases score --rescore-from RESULT_DIR`; it reads the six existing behavior answers, never reruns producers, and writes a separate result directory with source and contract digests.

Rescore an existing complete AIRI profile without changing its original files:

```bash
python3 scripts/run_forward_eval.py \
  --runtime claude-code \
  --model fable \
  --model-label deepseek-v4-pro \
  --reasoning-effort high \
  --phases score \
  --rescore-from evals/results/airi-v0.2-claude-code-ccswitch-deepseek-v4-pro-high-full-r3 \
  --repository-source ../airi \
  --rubric evals/rubrics/architecture-review-v2.md \
  --schema evals/rubrics/architecture-review-v2.schema.json \
  --output-dir evals/results/airi-v0.2-claude-v2-rescore
```

Run the pinned baseline from a clean sibling AIRI checkout:

```bash
python3 scripts/run_forward_eval.py \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-baseline
```

Each completed sample is atomically checkpointed before the next repetition. If the process is interrupted, resume the same execution profile:

```bash
python3 scripts/run_forward_eval.py \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-baseline \
  --resume
```

An execution profile is the runtime, runtime version, model, reasoning effort, per-call timeout, repository commit, Skill release, complete case digest, and concurrency settings recorded in the partial manifest. Never fill a missing repetition with a different model, agent runtime, effort level, or prompt definition. An incomplete run may only increase its hard timeout; the runner records the old and new values in `resume_history` and preserves failed attempts in `prior_failures`. Lowering the timeout or changing any other profile field is rejected. Compare a Claude Code or other provider run as a separate profile with its own output directory and thresholds; do not pool its samples with a Codex profile.

Run the complete Codex Luna/max profile with a timeout that accommodates its observed architecture-answer latency:

```bash
python3 scripts/run_forward_eval.py \
  --runtime codex \
  --model gpt-5.6-luna \
  --model-label gpt-5.6-luna \
  --reasoning-effort max \
  --repetitions 3 \
  --max-concurrency 3 \
  --call-timeout-seconds 1800 \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-codex-gpt-5.6-luna-max-full-r3
```

The committed Luna/max profile contains all 30 planned samples. It passes routing at 9/9 positive and 0/9 negative loads. Behavior averages 17.0/18 for control and 17.33/18 for treatment, so it fails the required two-point improvement. It also fails the strict generalization gate because two treatment scores do not list main, preload, and renderer together, although all three identify Electron as current and do not treat legacy Tauri as current. The initial 900-second run timed out three long samples; the recorded resume raised the hard timeout to 1800 seconds without changing the model, effort, repositories, prompts, or successful checkpoints.

For a one-repetition Claude Code routing profile managed by CCSwitch, where `fable` is the CLI alias and `deepseek-v4-pro` is the user-declared model label:

```bash
python3 scripts/run_forward_eval.py \
  --runtime claude-code \
  --model fable \
  --model-label deepseek-v4-pro \
  --reasoning-effort high \
  --phases routing \
  --repetitions 1 \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-claude-code-deepseek-v4-pro-high-routing-r1
```

The manifest keeps the configuration manager, CLI model argument, declared model label, and runtime-reported `observed_models` separate. This profile is exploratory and is not combined with a Codex profile.

Run the complete three-repetition Claude Code profile in a separate directory:

```bash
python3 scripts/run_forward_eval.py \
  --runtime claude-code \
  --model fable \
  --model-label deepseek-v4-pro \
  --reasoning-effort high \
  --repetitions 3 \
  --max-concurrency 3 \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-claude-code-ccswitch-deepseek-v4-pro-high-full-r3
```

The committed complete profile passes routing at 9/9 positive and 0/9 negative loads. It fails the behavior improvement gate because both variants saturate the current rubric at 18/18, despite scorers recording nine control factual errors and five treatment factual errors. It also fails generalization because treatment answers do not consistently identify main, preload, and renderer as current boundaries. These are baseline observations, not in-run remediation instructions.

The `--model` value is the configured Claude Code alias used by this environment; replace it for another setup. `--model-label` records the evaluator's declared provider model separately from the runtime alias and the model identifiers reported by Claude Code. Routing invocations use `dontAsk` permission mode with only `Read`, `Glob`, `Grep`, and the read-only `Skill` loader, and disable session persistence. This removes Bash and all editing tools instead of relying on Claude's plan mode, which may create user-level plan files. Omitting `Skill` invalidates routing measurements because the model cannot load a matched Skill. The default Claude profile stops a call after 720 seconds without retrying that timeout; the case-default Codex profile uses 900 seconds. An incomplete manifest preserves prior infrastructure failures and may resume with the same timeout or a larger one. A model argument, alias mapping, runtime, effort, permission mode, tool set, prompt change, or timeout decrease requires a new output directory and profile.

The MarkText Electron case is fixed at `cases/marktext-v0.2.json` and `marktext/marktext@e52106fd1cdcbd33c1258b7b0cdc7013c4c5d86c`, scoped to `packages/desktop`. Its initial Claude baseline achieved routing 9/9 positive and 0/9 negative loads, but the v2 scorer rejected two Treatment payloads and one Control payload for internally inconsistent structured fields. The committed result is therefore deliberately incomplete; it is evidence for scorer calibration, not evidence to add an Electron adapter or release v0.2.0.

The runner creates temporary control and treatment clones at the pinned repository commit, preserves repository Skills, installs only the released architecture Skill in treatment, and uses read-only ephemeral executions. It commits no checkpoint directory, partial manifest, session data, JSONL, temporary clones, credentials, provider configuration, or absolute local paths. A failed gate is retained as baseline evidence; remediation belongs in a later change.
