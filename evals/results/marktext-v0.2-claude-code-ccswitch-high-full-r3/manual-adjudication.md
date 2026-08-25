# MarkText v2 manual evidence adjudication — incomplete baseline

- Repository: `marktext/marktext@e52106fd1cdcbd33c1258b7b0cdc7013c4c5d86c`
- Scope: `packages/desktop`
- Profile: Claude Code + CCSwitch, `high`, three repetitions
- Routing: 9/9 positive loaded; 0/9 negative loaded
- Behavior producers: 6/6 completed
- Structured scores: 3/6 completed after one recovery attempt

## Evidence spot-check

The valid Treatment score identifies the current Electron 42 main/preload/renderer boundary, the typed `contextBridge` surface, `shared/types/ipc.ts`, the main-process event bus, window identity, the `@muyajs/core` editor-engine boundary, and buffered-state persistence. These are present at the pinned commit in `packages/desktop/src/main/index.ts`, `src/preload/index.ts`, `src/shared/types/ipc.ts`, `src/main/utils/internalIpc.ts`, `src/main/windows`, and the desktop package configuration. `CLAUDE.md` confirms the monorepo layout and sandboxed renderer intent.

The valid Treatment score also detected, rather than silently using, documentation drift: the CLAUDE architecture section refers to an old `config.js` and unsafe window settings while `src/main/config.ts` sets `contextIsolation: true`, `sandbox: true`, and `nodeIntegration: false`; website architecture/TypeScript pages describe a pre-monorepo layout. These conflicts were marked non-decision-relevant in the valid score.

## Completion decision

The baseline is intentionally **incomplete**. Treatment r1 and r3 returned internally inconsistent `unresolved_decision_conflict_count` values and were rejected by the v2 validator; Control r3 referenced an unknown score dimension and was also rejected. One recovery attempt reproduced the Treatment contract failures. The failed payloads are preserved in `manifest.json` under `prior_failures`; no Skill or original producer answer was changed.

Because the full Treatment score set is unavailable, this result cannot decide whether AIRI and MarkText share an Electron-boundary failure. Do not add an Electron adapter or publish `v0.2.0` from this baseline. A follow-up should first calibrate scorer-output reliability or run a new explicitly versioned scoring profile.

