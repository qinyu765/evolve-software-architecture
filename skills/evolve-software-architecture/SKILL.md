---
name: evolve-software-architecture
description: Evidence-based architecture guidance for existing repositories; evaluate boundaries, technical-debt direction, substantial new requirements, and incremental refactoring. Use when a decision changes module or process ownership, extensibility, compatibility, or cross-cutting design. Combine repository evidence with applicable technology Skills to compare trade-offs and produce a migration plan. Keep ordinary local fixes, styling, renames, and routine dependency updates focused unless they expose an architectural decision.
---

# Evolve Software Architecture

Lower future change cost through evidence-based, reversible architecture decisions. This Skill supplies the judgment workflow; relevant technology Skills supply platform constraints and implementation knowledge. It carries no built-in framework adapter or dependency catalog.

## Working boundary

Deliver a decision-ready recommendation and execution plan before changing code. Implement only when the user requests it, using applicable technology Skills and repository workflows. Cover existing-system reviews, structural refactoring, and substantial new requirements; do not expand a local task into a whole-repository review or introduce a separate greenfield workflow.

Keep **facts** (observed evidence), **inferences** (reasoned interpretations), **unknowns** (unestablished decision inputs), and **constraints** (limits the decision must respect) distinct where confusing them could change the recommendation. Use the user's language and the project's domain vocabulary.

## Establish context and technology support

Read repository instructions, manifests, entry points, relevant architecture documents, tests, and change history. Classify the system from multiple signals; directory names and a helper's file inventory are insufficient. Trace the relevant runtime or API flow, state ownership, module/process/trust boundaries, and failure paths before choosing a target design.

Use [assessment-framework.md](references/core/assessment-framework.md) for deeper investigation and evidence provenance. The optional read-only inventory helper is:

```bash
python3 <skill-root>/scripts/collect_repo_signals.py --repo <repository>
```

Follow [technology-context.md](references/technology-context.md) to select available, applicable technology Skills and reconcile their guidance with repository facts and constraints. Prefer verified maintainer-published Skills, then credible community Skills with inspectable provenance. Load only relevant guidance; names or marketplace placement do not establish official status.

**If no suitable technology Skill is installed and accessible, ask the user before substituting official documentation or proceeding with technology-dependent conclusions.** Explain the specific gap and offer documentation, a user-supplied Skill, or a narrower scope. Honor authorization already given for this task; do not ask again. While awaiting the answer, repository inventory and technology-independent analysis may continue. Do not install Skills automatically.

If the request already establishes that guidance and fallback authorization are missing, ask before a detailed review. Source inspection does not bypass that choice: do not deliver API/lifecycle compatibility advice or a migration recommendation under a “repository-only” or “generic” label. Limit the interim response to established scope/inventory and the concrete question, then wait for the answer.

## Investigate the decision

For an existing-system review, locate actual change amplification, missing ownership, or fragile interfaces. Separate symptoms from causes and real variation from hypothetical extensibility.

For a substantial new requirement:

- establish the intended behavior, compatibility commitments, and constraints;
- check existing APIs, implementation, configuration, tests, and history for capabilities that already satisfy part of the request;
- trace which boundaries, owners, consumers, and failure paths must change;
- compare extending the current seams with structural change before proposing a new abstraction.

Verify the current-state claims that drive a recommendation. Documentation may describe intent or an older implementation. Reconcile consequential disagreements with implementation, configuration, tests, and history; otherwise label the uncertainty and make the recommendation conditional or ask the user. A missing search result is not proof of absence. Do not recommend building an abstraction merely because it was not mentioned in a document.

## Compare and recommend

Use [quality-attributes.md](references/core/quality-attributes.md) to rank the few attributes governing the decision and state their trade-offs. Compare viable alternatives, including retaining or locally extending the current shape when defensible. Explain ownership, assumptions, migration cost, operational consequences, and evidence that would invalidate each option.

Recommend a direction supported by those drivers. Prefer small, meaningful interfaces over speculative layers. Give incremental steps, behavior/compatibility checks, rollback points, and observable completion criteria. Identify abstractions to defer and the signals that would justify them. Use [decision-record.md](references/core/decision-record.md) for decisions worth recording in an ADR.

## Deliver at the task's scale

Make scope and confidence, decisive evidence, current friction or requirement impact, quality-attribute priorities, alternatives, the recommendation, migration/verification, and consequential open decisions easy to find. Use a compact answer for a narrow boundary decision and a fuller review for a broad request; these are content requirements, not mandatory headings.

Identify the technology Skills or authorized documentation that materially informed the decision, their known provenance/version limits, and any unresolved gaps. Do not present their general practices as facts about this repository. Keep project-specific findings in the review or evaluation case rather than converting them into universal rules.
