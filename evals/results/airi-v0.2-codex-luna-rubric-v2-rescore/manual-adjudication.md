# AIRI v2 manual evidence adjudication — Codex Luna/max profile

- Repository: `moeru-ai/airi@5228f94123e42416435e7f7e8215df26f3bb065b`
- Source behavior profile: `codex-gpt-5-6-luna-max`
- Scored samples: 3 Control + 3 Treatment
- Adjudicator: manual repository inspection at the pinned commit

## Treatment decision

All three Treatment scores have zero material factual errors, zero unresolved decision-relevant documentation conflicts, and `accuracy.gate_pass = true`. Treatment totals are 17, 18, and 18. The two minor findings are a non-existent absolute evidence-link spelling and the absence of a current user-facing permission UI; both are limited evidence/usability corrections and do not overturn the architecture recommendation.

The following claims were checked against the pinned implementation and configuration:

- Current desktop: `apps/stage-tamagotchi` uses Electron, `electron-vite`, and `electron-builder`; the current checkout has no `crates/` directory.
- Runtime boundaries: the Electron main process and Injeca composition root, renderer/preload Eventa contexts, in-process `ExtensionHost`, plugin iframe boundary, HTTP/WebSocket service, and child-process services are all represented in the pinned source.
- Documentation drift: `multi-transport.md` is marked Planned and its node/web implementations throw for unsupported transports; `capability-orchestration.md` is Proposed; the architecture document is Active design. Treatment answers compared these documents with implementation and treated future modes as future rather than current behavior.

The Control set was checked as well. Its one material error is a counterfactual diagnostic and does not block the Treatment accuracy gate. The first scorer attempt for Control r3 returned internally inconsistent accuracy counts and was rejected by the schema validator; a single `--resume` recovery produced a valid sixth score. The invalid payload remains recorded in `prior_failures`.

No original AIRI behavior or score file was edited.

