# Evaluation status

The v0.1 XiLuoLin case remains the first vertical reference. The machine-readable `cases/airi-v0.2.json` definition is the single source of truth for the independent second-desktop routing and behavior baseline.

Run deterministic checks and inspect the 30-call plan without contacting a model:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_forward_eval.py --dry-run
```

Run the pinned baseline from a clean sibling AIRI checkout:

```bash
python3 scripts/run_forward_eval.py \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-baseline
```

Each completed sample is atomically checkpointed before the next repetition. If the process is interrupted, resume only the exact same execution profile:

```bash
python3 scripts/run_forward_eval.py \
  --airi-source ../airi \
  --output-dir evals/results/airi-v0.2-baseline \
  --resume
```

An execution profile is the runtime, runtime version, model, reasoning effort, per-call timeout, repository commit, Skill release, complete case digest, and concurrency settings recorded in the partial manifest. Never fill a missing repetition with a different model, agent runtime, effort level, timeout, or prompt definition. Compare a Claude Code or other provider run as a separate profile with its own output directory and thresholds; do not pool its samples with the pinned Codex baseline.

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

The manifest keeps the configuration manager, CLI model argument, declared model label, and runtime-reported `observed_models` separate. This profile is exploratory and is not combined with the fixed Codex baseline.

The `--model` value is the configured Claude Code alias used by this environment; replace it for another setup. `--model-label` records the evaluator's declared provider model separately from the runtime alias and the model identifiers reported by Claude Code. Routing invocations use `dontAsk` permission mode with only `Read`, `Glob`, `Grep`, and the read-only `Skill` loader, and disable session persistence. This removes Bash and all editing tools instead of relying on Claude's plan mode, which may create user-level plan files. Omitting `Skill` invalidates routing measurements because the model cannot load a matched Skill. The Claude profile stops a call after 720 seconds without retrying that timeout; the Codex profile uses 900 seconds. A model argument, alias mapping, runtime, effort, timeout, permission mode, tool set, or prompt change requires a new output directory and profile.

The runner creates temporary control and treatment clones at the pinned AIRI commit, preserves AIRI's repository Skills, installs only the released architecture Skill in treatment, and uses read-only ephemeral Codex executions. It commits no checkpoint directory, partial manifest, session data, JSONL, temporary clones, credentials, provider configuration, or absolute local paths. A failed gate is retained as baseline evidence; remediation belongs in a later change.
