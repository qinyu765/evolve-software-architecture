# Evaluation status

The v0.1 evaluation surface contains prompt cases and a scoring rubric. It does not yet claim measured model-trigger precision or cross-project generalization.

Deterministic validation covers Skill structure, metadata, release-pinned vendoring, lock correctness, drift refusal, and public installer compatibility. Isolated model-based forward tests are a v0.2 gate and must run without leaking the intended answer or XiLuoLin-specific conclusions into the evaluator.
