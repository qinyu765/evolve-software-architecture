# ADR-0004: Keep a generic core and use companion technology Skills

- Status: accepted
- Date: 2026-10-01
- Scope: installable Skill, lifecycle boundary, and v0.2.0 acceptance
- Supersedes: ADR-0001's built-in adapter expansion strategy; retains its single-Skill distribution decision.

## Context and drivers

The AIRI and MarkText evaluations established trigger precision but exposed current-state errors, overlooked existing capabilities, and inconsistent discovery of runtime boundaries. Scorer calibration is complete enough to retain that evidence. Adding and maintaining a framework adapter for every project type would expand maintenance faster than the architecture method itself.

The maintainer wants a usable general Skill now, lower update frequency, and technology guidance supplied by the project's available Skills. Missing guidance must not silently become permission to substitute documentation or install dependencies.

## Decision

Keep evidence, boundary discovery, deliberate trade-offs, alternatives, migration, and verification in a single generic Skill. Cover existing repositories, structural refactoring, and substantial new requirements; implementation remains conditional on the user's request. Do not add a separate greenfield mode.

Prefer available, applicable maintainer-published technology Skills, then community Skills with inspectable provenance. Treat their guidance as constraints and implementation knowledge, not a predetermined architecture. When a required Skill or material coverage is missing, ask before documentation fallback unless the current task already authorizes it. Do not automate installation or maintain a dependency catalog.

Archive the v0.1.2 Tauri and adapter-selection references outside the package. Replace them with technology-context cooperation guidance. Use existing-repository and major-requirement cases across AIRI and Click for a compact, independent acceptance pass. Preserve the historical desktop scoring contracts, matrices, and model policy; their Electron-only generalization and two-point gain requirements do not define v0.2.0 acceptance.

## Consequences and limits

The package name, installation paths, implicit invocation, and vendor-lock format stay compatible. The guidance and references change; pinned old releases remain reproducible. No project copy updates automatically.

This release establishes usable cross-type behavior, not statistically measured gains over all base models. Source-specific facts remain in cases. Core changes need demonstrated portable failures or cross-type evidence; technology release churn is handled at use time rather than copied into this package.

Revisit when real usage demonstrates a missing generic decision step, companion conflicts cannot be resolved, trigger precision regresses, or users request a distinct lifecycle with its own acceptance criteria.
