# AIRI v2 manual evidence adjudication — Claude Code profile

- Repository: `moeru-ai/airi@5228f94123e42416435e7f7e8215df26f3bb065b`
- Source behavior profile: `claude-code-ccswitch-deepseek-v4-pro-high`
- Scored samples: 3 Control + 3 Treatment
- Adjudicator: manual repository inspection at the pinned commit

## Treatment decision

All three Treatment scores have `total = 18`, zero material factual errors, zero unresolved decision-relevant documentation conflicts, and `accuracy.gate_pass = true`. The reported minor errors are limited to imprecise counts, line ranges, file attribution, or over-broad wording; none changes the recommendation or current-platform classification.

The following claims were checked against the pinned implementation and configuration:

- Current desktop: `apps/stage-tamagotchi` uses Electron, `electron-vite`, and `electron-builder`; the current checkout has no `crates/` directory.
- Runtime boundaries: main-process composition in `apps/stage-tamagotchi/src/main/index.ts`, per-window Eventa/IPC contexts under `src/main/windows`, plugin-host execution in `packages/plugin-sdk`, and the `/ws` server in `packages/server-runtime` are present at the pinned commit.
- Documentation drift: `AGENTS.md` describes `crates/` as legacy, while the directory is absent; the answer marked this as historical/non-current. Plugin design documents mark multi-transport work Planned or describe active intent, while node/web transport implementations throw for unsupported transports; the answers either marked this as resolved or did not use it as current behavior.
- The `/ws` handler and server-side `peer:authenticate`/`extension:announce` paths exist, so the scorer's correction of the “client-only stub” wording is warranted.

One Control sample was also checked. Its `crates/` observation is a diagnostic stale-documentation issue, not a Treatment gate failure. No original behavior answer or score was edited.

