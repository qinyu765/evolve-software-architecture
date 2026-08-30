# Evaluation fixtures

Fixtures are small, synthetic repository fragments used to test project-type detection and architecture-output quality without copying a complete public repository.

The XiLuoLin case references a public commit and is inspected in a temporary checkout. Add a fixture only when a scenario cannot be represented safely by a prompt and a public source reference. Keep fixture names tied to project type, not to a framework preference.

`scorer-v2.1-regressions.json` contains manually adjudicated scorer payloads for deterministic validation of the v2.1 accuracy contract. These fixtures lock material/minor, decision-relevance, and schema-identifier boundaries; they do not rerun a model or replace repository-level factual review.
