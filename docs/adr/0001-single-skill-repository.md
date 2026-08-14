# ADR-0001: Start with one focused Skill

- Status: accepted
- Date: 2026-08-14
- Scope: repository and distribution shape

## Context

The first real validation target is XiLuoLin, a Desktop/Tauri application. The long-term goal is architecture guidance for different project types and lifecycle stages. A multi-Skill collection would increase trigger collisions, release surface, and maintenance cost before the architecture workflow has been validated.

## Decision drivers

- reliable triggering for architecture decisions;
- portable core reasoning with project-type adapters;
- low initial release and evaluation complexity;
- a clear path to add adapters without turning the first release into a general engineering suite.

## Options considered

1. A single focused Skill with a core and project-type references.
2. A multi-Skill architecture collection with a router.
3. A broad engineering Skill suite covering architecture, implementation, review, and delivery.

## Decision

Start with `evolve-software-architecture` as one focused Skill. Add adapters inside its references and introduce separate Skills only when a distinct workflow has its own trigger, output contract, and evaluation surface.

## Consequences

The first repository has one public installation target and a small trigger surface. More project types are added through the adapter contract. A future split must preserve the core output contract or record a superseding ADR.

## Revisit conditions

Reconsider the repository boundary when adapter selection becomes ambiguous, the Skill's `SKILL.md` cannot stay under 500 lines, or a second workflow needs independent lifecycle and release semantics.
