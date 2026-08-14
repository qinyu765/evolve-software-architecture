# Roadmap

The roadmap expands one axis at a time so a failure can be attributed to a project adapter or a lifecycle workflow.

## v0.1 — XiLuoLin vertical slice

- Core evidence-first architecture review workflow.
- Desktop/Tauri adapter.
- Structured Markdown output contract.
- Positive and negative trigger cases.
- Controlled vendor copy into XiLuoLin only after the release tag exists.

## v0.2 — Desktop generalization

- Validate against a second desktop repository.
- Add drift checking and release-to-project synchronization.
- Promote only platform invariants or repeated desktop findings.

## v0.3 — Non-UI stress test

- Add an SDK adapter.
- Test public API evolution, compatibility, versioning, consumers, and release contracts.
- Keep desktop assumptions out of the core.

## v0.4 — Lifecycle expansion

- Add explicit guidance for substantial new requirements.
- Add a greenfield/new-project mode only after the existing-repository workflow passes across different project types.

## v1.0 — General-purpose architecture Skill

- Validate against Desktop, SDK, and Web or CLI repositories.
- Maintain a project-type adapter contract.
- Keep the core free of framework-specific assumptions.
- Publish stable release and vendor-update procedures.

## Promotion gates

- XiLuoLin-specific facts stay in its evaluation case.
- A desktop rule needs a platform invariant or two independent desktop repositories.
- A core rule needs evidence from two materially different project types.
- A lifecycle trigger expands only after the current-repository workflow has stable positive and negative evaluations.
