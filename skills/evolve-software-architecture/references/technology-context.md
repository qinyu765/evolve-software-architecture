# Technology context and companion Skills

This Skill owns architecture reasoning: evidence, boundaries, quality-attribute trade-offs, alternatives, migration, and verification. Companion Skills contribute technology-specific constraints and implementation knowledge; they do not decide the architecture automatically.

## Select from the actual environment

Identify the technologies and versions involved in the decision from manifests, configuration, entry points, and runtime paths. A mixed repository may need guidance for more than one technology, but load only what the affected boundary requires.

Inspect the Skill catalog provided by the environment and relevant project-installed Skills where accessible. Select by actual scope, availability, and version applicability. Prefer a Skill published by the technology's maintainer when its provenance can be verified; otherwise use credible community guidance with inspectable source and relevant coverage. A familiar name, installer listing, or author assertion alone does not prove official status. Report unknown provenance honestly.

Read the selected Skill's instructions and only the references needed by this task. Do not duplicate its manuals, maintain a list of preferred Skills here, or assume a particular runtime has an invocation API. Use the environment's supported loading mechanism; if a listed Skill cannot be accessed, treat it as unavailable.

## Missing or incomplete guidance

When no suitable installed Skill covers the needed technology, explain the gap and ask the user to choose official documentation, supplying a suitable Skill, or narrowing the analysis. Do not install anything or substitute documentation before the answer. If the user already authorized that fallback for the current task, proceed without repeating the question.

An installed Skill can also have a material coverage or version gap. State it rather than inventing support; use already-authorized documentation or ask before substituting it. Available guidance for a renderer does not by itself cover native process isolation or another runtime's lifecycle.

While waiting, continue inspection and technology-independent reasoning where useful, but stop conclusions and implementation steps that depend on the missing knowledge. If documentation is authorized, prefer the maintainer's sources for the repository's version; distinguish current documentation from older repository behavior.

## Resolve disagreements through the decision

User intent and explicit constraints govern the assignment. Repository instructions and verified implementation establish local requirements and current behavior. Companion advice is a technology practice to assess, not evidence that a local pattern is wrong or absent.

When guidance conflicts, name the disputed recommendation, the local evidence or constraint, and its consequence. Resolve factual/version questions with appropriate sources and history. If a remaining product or ownership decision changes the outcome, ask the user or present conditional options instead of silently selecting a convention. Do not turn a companion's rewrite, preferred framework, or review checklist into additional authorized work.

Report the Skills or documentation that materially informed the result, any known source/version limits, and the uncertainties that still affect the recommendation. Avoid listing unrelated installed Skills.
