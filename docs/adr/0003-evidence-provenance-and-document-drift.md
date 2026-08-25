# ADR-0003: Treat evidence provenance and document drift as first-class review data

- Status: accepted
- Date: 2026-08-25
- Scope: evaluation rubric and evidence-first architecture workflow

## Context

Repository documentation can describe intent, history, or a previous implementation rather than current behavior. Treating every document as current fact causes architecture reviews to reward confident use of stale information. Treating implementation as an absolute source is also insufficient when code is generated, dead, migrated, or split across runtime paths.

## Decision drivers

- Preserve the nine-dimension score and historical comparability.
- Distinguish model factual errors from repository-level source conflicts.
- Make current behavior claims auditable at a pinned commit.
- Keep the rule portable across desktop, SDK, Web, CLI, and other project types.

## Decision

Record claim-level evidence provenance and classify conflicts as historical, conflict, unknown, or resolved. Use implementation, configuration, tests, build scripts, history, ADRs, documentation, and user input according to the claim being checked. Add a separate Treatment accuracy gate; do not turn accuracy into a tenth score dimension.

## Consequences

The scorer reports factual errors and documentation drift separately. A material error or unresolved decision-relevant conflict blocks Treatment, while Control errors remain diagnostic. Original evaluation profiles remain immutable; rescoring uses a new rubric digest and result directory.

## Revisit conditions

Revisit when two materially different project types show that the provenance categories cannot represent their current/intent/history distinction, or when deterministic fixtures produce false accuracy failures.
