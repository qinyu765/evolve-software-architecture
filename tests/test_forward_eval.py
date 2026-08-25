from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_forward_eval import (
    AttemptResult,
    EvaluationError,
    Invocation,
    aggregate_results,
    assert_control_uncontaminated,
    build_invocation_matrix,
    build_score_invocation_matrix,
    case_digest,
    claude_command,
    execute_with_retry,
    frontmatter_bytes,
    inject_routing_marker,
    load_json,
    main,
    parse_claude_output,
    redact_text,
    redact_value,
    run_case_groups,
    scorer_prompt,
    skill_parent,
    summary_markdown,
    validate_score,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "evals" / "cases" / "airi-v0.2.json"
MARKTEXT_CASE_PATH = ROOT / "evals" / "cases" / "marktext-v0.2.json"


class ForwardEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = load_json(CASE_PATH)

    def test_default_matrix_has_exactly_thirty_independent_calls(self) -> None:
        matrix = build_invocation_matrix(self.case, 3)
        self.assertEqual(len(matrix), 30)
        self.assertEqual(len({item.id for item in matrix}), 30)
        self.assertEqual(sum(item.phase == "routing" for item in matrix), 18)
        self.assertEqual(sum(item.phase == "behavior" for item in matrix), 6)
        self.assertEqual(sum(item.phase == "score" for item in matrix), 6)

    def test_marktext_dry_run_has_exactly_thirty_calls(self) -> None:
        case = load_json(MARKTEXT_CASE_PATH)
        matrix = build_invocation_matrix(case, 3, "claude-code")
        self.assertEqual(len(matrix), 30)
        self.assertEqual(sum(item.phase == "routing" for item in matrix), 18)
        self.assertEqual(sum(item.phase == "behavior" for item in matrix), 6)
        self.assertEqual(sum(item.phase == "score" for item in matrix), 6)

    def test_score_only_matrix_has_exactly_six_scorers(self) -> None:
        matrix = build_score_invocation_matrix(self.case, 3)
        self.assertEqual(len(matrix), 6)
        self.assertTrue(all(item.phase == "score" for item in matrix))
        self.assertEqual(len({item.id for item in matrix}), 6)

    def test_score_phase_rescores_answers_without_running_producers(self) -> None:
        score = self._score_payload()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-results"
            output = root / "rescore-results"
            source.mkdir()
            source_manifest = {
                "case": {"id": self.case["id"], "sha256": case_digest(self.case)},
                "repository": self.case["repository"],
                "skill": self.case["skill"],
                "profile": {"runtime": "codex", "repetitions": 3, "profile_id": "fixture"},
                "results": [],
            }
            for invocation in build_invocation_matrix(self.case, 3):
                if invocation.phase != "behavior":
                    continue
                source_manifest["results"].append(
                    {"id": invocation.id, "success": True, "attempts": 1}
                )
                answer_path = source / "answers" / "behavior" / f"{invocation.id}.md"
                answer_path.parent.mkdir(parents=True, exist_ok=True)
                answer_path.write_text("fixture producer answer\n", encoding="utf-8")
            write_json(source / "manifest.json", source_manifest)
            write_json(source / "summary.json", {"dataset_complete": True})
            source_manifest_bytes = (source / "manifest.json").read_bytes()

            def scorer(invocation, *_args, **_kwargs):
                self.assertEqual(invocation.phase, "score")
                return AttemptResult(0, json.dumps(score))

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch(
                    "scripts.run_forward_eval.prepare_checkouts",
                    return_value={"control": source, "treatment": source},
                ),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=scorer) as run,
            ):
                result = main(
                    [
                        "--runtime",
                        "codex",
                        "--repository-source",
                        str(source),
                        "--phases",
                        "score",
                        "--rescore-from",
                        str(source),
                        "--rubric",
                        str(ROOT / "evals" / "rubrics" / "architecture-review-v2.md"),
                        "--schema",
                        str(ROOT / "evals" / "rubrics" / "architecture-review-v2.schema.json"),
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertEqual(run.call_count, 6)
            self.assertEqual((source / "manifest.json").read_bytes(), source_manifest_bytes)
            manifest = load_json(output / "manifest.json")
            self.assertEqual(manifest["planned_calls"], 6)
            self.assertEqual(manifest["rescore_source"]["contract_status"], "legacy-unrecorded")

    def test_score_phase_requires_rescore_source(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "requires --rescore-from"):
            main(["--phases", "score"])

    def test_v2_score_requires_accuracy_and_documentation_drift_fields(self) -> None:
        score = self._score_payload()
        validate_score(score, require_accuracy=True)
        missing = dict(score)
        missing.pop("accuracy")
        with self.assertRaisesRegex(EvaluationError, "accuracy"):
            validate_score(missing, require_accuracy=True)

    def test_material_treatment_error_blocks_accuracy_gate(self) -> None:
        summary = self._aggregate_with_accuracy(
            treatment_accuracy={
                "material_error_count": 1,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": False,
            }
        )
        self.assertFalse(summary["gates"]["accuracy"])
        self.assertFalse(summary["gates"]["overall"])

    def test_unresolved_decision_documentation_conflict_blocks_accuracy_gate(self) -> None:
        summary = self._aggregate_with_accuracy(
            treatment_accuracy={
                "material_error_count": 0,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 1,
                "gate_pass": False,
            },
            documentation_drift=[
                {
                    "claim": "sandbox state",
                    "documentation_evidence": "CLAUDE.md",
                    "implementation_evidence": "BrowserWindow config",
                    "state": "conflict",
                    "decision_relevant": True,
                }
            ],
        )
        self.assertFalse(summary["gates"]["accuracy"])
        self.assertFalse(summary["gates"]["overall"])

    def test_minor_treatment_error_does_not_block_accuracy_gate(self) -> None:
        summary = self._aggregate_with_accuracy(
            treatment_accuracy={
                "material_error_count": 0,
                "minor_error_count": 1,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": True,
            }
        )
        self.assertTrue(summary["gates"]["accuracy"])

    def test_control_accuracy_error_is_diagnostic_only(self) -> None:
        summary = self._aggregate_with_accuracy(
            treatment_accuracy={
                "material_error_count": 0,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": True,
            },
            control_accuracy={
                "material_error_count": 1,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": False,
            },
        )
        self.assertTrue(summary["gates"]["accuracy"])
        self.assertEqual(summary["behavior"]["control"]["material_factual_errors"], 3)

    def test_acknowledged_documentation_conflict_does_not_block_accuracy_gate(self) -> None:
        summary = self._aggregate_with_accuracy(
            treatment_accuracy={
                "material_error_count": 0,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": True,
            },
            documentation_drift=[
                {
                    "claim": "sandbox state",
                    "documentation_evidence": "CLAUDE.md",
                    "implementation_evidence": "BrowserWindow config",
                    "state": "conflict",
                    "decision_relevant": True,
                }
            ],
        )
        self.assertTrue(summary["gates"]["accuracy"])
        self.assertEqual(summary["behavior"]["treatment"]["documentation_drifts"], 3)

    def _score_payload(self, accuracy=None, documentation_drift=None):
        dimensions = {name: 2 for name in (
            "scope_and_classification",
            "evidence",
            "current_friction",
            "quality_attributes",
            "options",
            "recommendation",
            "migration",
            "verification",
            "generalization",
        )}
        return {
            "dimensions": dimensions,
            "total": 18,
            "acceptance_checks": {
                "current_desktop_platform": "Electron",
                "runtime_boundaries_identified": ["main", "preload", "renderer"],
                "legacy_platform_treated_as_current": False,
            },
            "accuracy": accuracy or {
                "material_error_count": 0,
                "minor_error_count": 0,
                "unresolved_decision_conflict_count": 0,
                "gate_pass": True,
            },
            "factual_errors": [],
            "documentation_drift": documentation_drift or [],
            "rationale": "fixture",
        }

    def _aggregate_with_accuracy(
        self, treatment_accuracy, documentation_drift=None, control_accuracy=None
    ):
        marker = self.case["routing"]["marker_token"]
        routing = []
        for index in range(9):
            invocation = Invocation(
                f"positive-{index}", "routing", f"p-{index}", "positive", 1, "p"
            )
            routing.append(type("Result", (), {"invocation": invocation, "success": True, "answer": marker})())
        for index in range(9):
            invocation = Invocation(
                f"negative-{index}", "routing", f"n-{index}", "negative", 1, "p"
            )
            routing.append(type("Result", (), {"invocation": invocation, "success": True, "answer": "plain"})())
        scores = {}
        for variant in ("control", "treatment"):
            for repetition in range(1, 4):
                accuracy = (
                    treatment_accuracy
                    if variant == "treatment"
                    else control_accuracy
                )
                scores[f"score-{variant}-r{repetition}"] = self._score_payload(
                    accuracy=accuracy,
                    documentation_drift=documentation_drift if variant == "treatment" else [],
                )
        return aggregate_results(self.case, routing, scores, [])

    def test_marker_injection_preserves_frontmatter_bytes(self) -> None:
        content = b"---\nname: example\ndescription: example\n---\n\n# Body\n"
        injected = inject_routing_marker(content, "[marker]")
        self.assertEqual(frontmatter_bytes(injected), frontmatter_bytes(content))
        self.assertIn(b"[marker]", injected)
        self.assertEqual(injected.count(b"# Body"), 1)

    def test_scorer_prompt_does_not_leak_expected_platform(self) -> None:
        prompt = scorer_prompt("request", "answer", "rubric")
        self.assertNotIn("Electron", prompt)
        self.assertNotIn("Tauri", prompt)

    def test_control_contamination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            assert_control_uncontaminated(repo)
            (repo / ".agents" / "skills" / "evolve-software-architecture").mkdir(
                parents=True
            )
            with self.assertRaisesRegex(RuntimeError, "control checkout"):
                assert_control_uncontaminated(repo)

    def test_retry_occurs_once_for_provider_failure(self) -> None:
        invocation = Invocation("x", "routing", "case", "positive", 1, "prompt")
        attempts = iter(
            [
                AttemptResult(1, "", stderr="provider timed out"),
                AttemptResult(0, "answer"),
            ]
        )
        checks = []
        result = execute_with_retry(
            invocation,
            lambda _: next(attempts),
            lambda: checks.append(True),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(checks), 4)

    def test_hard_timeout_is_not_retried(self) -> None:
        invocation = Invocation("x", "routing", "case", "positive", 1, "prompt")
        calls = []

        def timed_out(_invocation):
            calls.append(True)
            return AttemptResult(
                124,
                "",
                stderr="evaluation call timed out after 720 seconds",
                metadata={"timed_out": True},
            )

        result = execute_with_retry(invocation, timed_out, lambda: None)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.metadata["timed_out"])

    def test_case_digest_changes_when_a_prompt_changes(self) -> None:
        changed = json.loads(json.dumps(self.case))
        changed["routing"]["negative"][0]["prompt"] += " changed"
        self.assertNotEqual(case_digest(self.case), case_digest(changed))

    def test_case_stops_after_two_consecutive_failed_repetitions(self) -> None:
        invocations = [
            Invocation(f"case-r{index}", "routing", "case", "positive", index, "p")
            for index in (1, 2, 3)
        ]

        def run_one(invocation: Invocation):
            return type("Result", (), {"invocation": invocation, "success": False})()

        checkpointed = []
        results, skipped = run_case_groups(
            invocations, 3, 3, run_one, lambda result: checkpointed.append(result.invocation.id)
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(checkpointed, ["case-r1", "case-r2"])
        self.assertEqual(skipped, ["case-r3"])

    def test_checkpointed_success_resets_consecutive_failure_streak(self) -> None:
        invocations = [
            Invocation(f"case-r{index}", "routing", "case", "positive", index, "p")
            for index in (1, 3, 4)
        ]

        def run_one(invocation: Invocation):
            return type("Result", (), {"invocation": invocation, "success": False})()

        results, skipped = run_case_groups(
            invocations,
            4,
            1,
            run_one,
            successful_repetitions={("case", 2)},
        )
        self.assertEqual([result.invocation.id for result in results], [
            "case-r1",
            "case-r3",
            "case-r4",
        ])
        self.assertEqual(skipped, [])

    def test_score_aggregation_applies_all_gates(self) -> None:
        marker = self.case["routing"]["marker_token"]
        routing = []
        for index in range(9):
            invocation = Invocation(
                f"positive-{index}", "routing", f"p-{index}", "positive", 1, "p"
            )
            routing.append(type("Result", (), {"invocation": invocation, "success": True, "answer": marker})())
        for index in range(9):
            invocation = Invocation(
                f"negative-{index}", "routing", f"n-{index}", "negative", 1, "p"
            )
            routing.append(type("Result", (), {"invocation": invocation, "success": True, "answer": "plain"})())
        dimensions = {
            "scope_and_classification": 2,
            "evidence": 2,
            "current_friction": 2,
            "quality_attributes": 2,
            "options": 2,
            "recommendation": 2,
            "migration": 2,
            "verification": 1,
            "generalization": 1,
        }
        checks = {
            "current_desktop_platform": "Electron",
            "runtime_boundaries_identified": ["main", "preload", "renderer"],
            "legacy_platform_treated_as_current": False,
        }
        scores = {}
        for variant, total in (("control", 12), ("treatment", 16)):
            for repetition in range(1, 4):
                values = dict(dimensions)
                if variant == "control":
                    values["evidence"] = 1
                    values["migration"] = 1
                    values["verification"] = 0
                    values["generalization"] = 0
                self.assertEqual(sum(values.values()), total)
                scores[f"score-{variant}-r{repetition}"] = {
                    "dimensions": values,
                    "total": total,
                    "acceptance_checks": checks,
                    "factual_errors": [],
                    "rationale": "test",
                }
        summary = aggregate_results(self.case, routing, scores, [])
        self.assertTrue(summary["dataset_complete"])
        self.assertTrue(summary["gates"]["routing"])
        self.assertTrue(summary["gates"]["behavior"])
        self.assertTrue(summary["gates"]["generalization"])
        self.assertTrue(summary["gates"]["overall"])

    def test_redaction_removes_known_and_home_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            known = Path(temporary).resolve()
            text = f"{known}/control /Users/alice/project /home/bob/repo"
            redacted = redact_text(text, [known])
            self.assertNotIn(str(known), redacted)
            self.assertNotIn("alice", redacted)
            self.assertNotIn("bob", redacted)

    def test_redaction_removes_symlink_spelling_and_eval_temp_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            eval_path = (
                "/var/folders/fs/example/T/airi-forward-eval-checkouts-abc/control"
            )
            escaped_eval_path = eval_path.replace("/", r"\/")
            redacted = redact_text(
                f"{link}/file {eval_path}/file {escaped_eval_path}/file "
                f"[evidence](<{eval_path}/file>)",
                [link],
            )
            self.assertNotIn(str(link), redacted)
            self.assertNotIn("airi-forward-eval-checkouts-abc", redacted)
            self.assertIn("[evidence](</evaluation-path/control/file>)", redacted)

    def test_redact_value_recurses_into_structured_scores(self) -> None:
        value = {
            "rationale": "/Users/alice/repo",
            "factual_errors": [
                {"repository_evidence": "/var/folders/fs/example/T/airi-forward-eval-checkouts-abc/control"}
            ],
        }
        redacted = redact_value(value)
        self.assertNotIn("alice", redacted["rationale"])
        self.assertNotIn(
            "airi-forward-eval-checkouts-abc",
            redacted["factual_errors"][0]["repository_evidence"],
        )

    def test_dry_run_does_not_require_codex(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "run_forward_eval.py"),
                "--dry-run",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            env={"PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(len(json.loads(result.stdout)), 30)
        self.assertIn("planned_agent_calls=30", result.stderr)

    def test_claude_profile_uses_configured_model_and_high_effort(self) -> None:
        command = claude_command(None, "high")
        self.assertIn("--no-session-persistence", command)
        self.assertIn("dontAsk", command)
        self.assertIn("Read,Glob,Grep,Skill", command)
        self.assertIn("high", command)
        self.assertIn('{"mcpServers":{}}', command)
        self.assertNotIn("--model", command)
        self.assertEqual(skill_parent("claude-code"), Path(".claude/skills"))

    def test_claude_schema_omits_unsupported_draft_declaration(self) -> None:
        command = claude_command(None, "high", ROOT / "evals" / "rubrics" / "architecture-review.schema.json")
        schema = json.loads(command[command.index("--json-schema") + 1])
        self.assertNotIn("$schema", schema)
        self.assertEqual(schema["type"], "object")

    def test_claude_result_reports_observed_model(self) -> None:
        answer, metadata = parse_claude_output(
            json.dumps(
                {
                    "result": "answer",
                    "duration_ms": 12,
                    "num_turns": 2,
                    "modelUsage": {"configured-model-id": {"inputTokens": 1}},
                }
            ),
            structured=False,
        )
        self.assertEqual(answer, "answer")
        self.assertEqual(metadata["observed_models"], ["configured-model-id"])

    def test_one_repetition_routing_profile_scales_thresholds(self) -> None:
        marker = self.case["routing"]["marker_token"]
        matrix = [
            item
            for item in build_invocation_matrix(self.case, 1, "claude-code")
            if item.phase == "routing"
        ]
        self.assertEqual(len(matrix), 6)
        results = [
            type(
                "Result",
                (),
                {
                    "invocation": item,
                    "success": True,
                    "answer": marker if item.variant == "positive" else "plain",
                },
            )()
            for item in matrix
        ]
        summary = aggregate_results(
            self.case, results, {}, [], repetitions=1, phases="routing"
        )
        self.assertTrue(summary["dataset_complete"])
        self.assertEqual(
            summary["routing_thresholds"],
            {"positive_minimum_loaded": 3, "negative_maximum_loaded": 0},
        )
        self.assertIsNone(summary["gates"]["behavior"])
        self.assertTrue(summary["gates"]["overall"])
        rendered = summary_markdown(summary)
        self.assertIn("# AIRI v0.2 routing profile", rendered)
        self.assertNotIn("## Behavior", rendered)
        self.assertIn("Overall for executed phases", rendered)

    def test_claude_case_records_ccswitch_configuration_manager(self) -> None:
        self.assertEqual(
            self.case["claude_code"]["configuration_manager"], "CCSwitch"
        )

    def test_completed_sample_checkpoint_can_resume_exact_profile(self) -> None:
        marker = self.case["routing"]["marker_token"]
        dimensions = {
            "scope_and_classification": 2,
            "evidence": 2,
            "current_friction": 2,
            "quality_attributes": 2,
            "options": 2,
            "recommendation": 2,
            "migration": 2,
            "verification": 2,
            "generalization": 2,
        }
        score = {
            "dimensions": dimensions,
            "total": 18,
            "acceptance_checks": {
                "current_desktop_platform": "Electron",
                "runtime_boundaries_identified": ["main", "preload", "renderer"],
                "legacy_platform_treated_as_current": False,
            },
            "factual_errors": [],
            "rationale": "fixture",
        }

        def fake_run(invocation, *_args, **_kwargs):
            if invocation.phase == "score":
                answer = json.dumps(score)
            elif invocation.phase == "routing" and invocation.variant == "positive":
                answer = marker
            else:
                answer = "fixture answer"
            return AttemptResult(0, answer)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output = temporary_path / "results"
            source = temporary_path / "airi"
            source.mkdir()
            checkouts = {"control": source, "treatment": source}
            arguments = [
                "--airi-source",
                str(source),
                "--output-dir",
                str(output),
            ]
            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=fake_run) as run,
            ):
                self.assertEqual(main(arguments), 0)
                self.assertEqual(run.call_count, 30)

            manifest_path = output / "manifest.json"
            manifest = load_json(manifest_path)
            checkpoint_id = "routing-positive-desktop-boundary-review-r1"
            checkpoint = next(
                record for record in manifest["results"] if record["id"] == checkpoint_id
            )
            identity = {
                key: manifest[key]
                for key in ("case", "repository", "skill", "profile", "planned_calls")
            }
            manifest_path.unlink()
            write_json(
                output / "partial-manifest.json",
                {
                    "schema_version": 1,
                    "identity": identity,
                    "started_at": manifest["started_at"],
                },
            )
            write_json(output / ".checkpoints" / f"{checkpoint_id}.json", checkpoint)

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=fake_run) as run,
            ):
                self.assertEqual(main([*arguments, "--resume"]), 0)
                self.assertEqual(run.call_count, 29)
            self.assertTrue(manifest_path.is_file())
            self.assertFalse((output / "partial-manifest.json").exists())
            self.assertFalse((output / ".checkpoints").exists())

    def test_incomplete_manifest_resumes_only_failed_scorers(self) -> None:
        marker = self.case["routing"]["marker_token"]
        dimensions = {name: 2 for name in (
            "scope_and_classification",
            "evidence",
            "current_friction",
            "quality_attributes",
            "options",
            "recommendation",
            "migration",
            "verification",
            "generalization",
        )}
        score = {
            "dimensions": dimensions,
            "total": 18,
            "acceptance_checks": {
                "current_desktop_platform": "Electron",
                "runtime_boundaries_identified": ["main", "preload", "renderer"],
                "legacy_platform_treated_as_current": False,
            },
            "factual_errors": [],
            "rationale": "fixture",
        }

        def producer_with_failed_scorer(invocation, *_args, **_kwargs):
            if invocation.phase == "score":
                return AttemptResult(1, "", stderr="invalid schema")
            if invocation.phase == "routing" and invocation.variant == "positive":
                return AttemptResult(0, marker)
            return AttemptResult(0, "fixture answer")

        def successful_scorer(invocation, *_args, **_kwargs):
            self.assertEqual(invocation.phase, "score")
            return AttemptResult(0, json.dumps(score))

        def second_failed_scorer(invocation, *_args, **_kwargs):
            self.assertEqual(invocation.phase, "score")
            return AttemptResult(1, "", stderr="invalid schema")

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output = temporary_path / "results"
            source = temporary_path / "airi"
            source.mkdir()
            checkouts = {"control": source, "treatment": source}
            arguments = [
                "--airi-source",
                str(source),
                "--output-dir",
                str(output),
            ]
            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=producer_with_failed_scorer),
            ):
                self.assertEqual(main(arguments), 2)

            first_manifest = load_json(output / "manifest.json")
            self.assertEqual(
                sum(not record["success"] for record in first_manifest["results"]), 6
            )

            real_write_json = write_json

            def interrupt_before_checkpoint_reconstruction(path, value):
                if path.parent.name == ".checkpoints":
                    raise RuntimeError("interrupted checkpoint reconstruction")
                real_write_json(path, value)

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.write_json", side_effect=interrupt_before_checkpoint_reconstruction),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "interrupted checkpoint reconstruction"
                ):
                    main(
                        [
                            *arguments,
                            "--resume",
                            "--call-timeout-seconds",
                            "1800",
                        ]
                    )
            self.assertFalse((output / "partial-manifest.json").exists())

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=second_failed_scorer) as run,
            ):
                self.assertEqual(
                    main(
                        [
                            *arguments,
                            "--resume",
                            "--call-timeout-seconds",
                            "1800",
                        ]
                    ),
                    2,
                )
                self.assertEqual(run.call_count, 6)

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=successful_scorer) as run,
            ):
                self.assertEqual(
                    main(
                        [
                            *arguments,
                            "--resume",
                            "--call-timeout-seconds",
                            "1800",
                        ]
                    ),
                    0,
                )
                self.assertEqual(run.call_count, 6)

            final_manifest = load_json(output / "manifest.json")
            self.assertEqual(len(final_manifest["prior_failures"]), 12)
            self.assertEqual(
                {record["error"] for record in final_manifest["prior_failures"]},
                {"invalid schema"},
            )
            self.assertEqual(final_manifest["profile"]["call_timeout_seconds"], 1800)
            self.assertEqual(
                final_manifest["resume_history"],
                [
                    {
                        "previous_call_timeout_seconds": 900,
                        "call_timeout_seconds": 1800,
                    }
                ],
            )
            self.assertTrue(load_json(output / "summary.json")["dataset_complete"])

    def test_newer_partial_state_rejects_timeout_decrease_before_checkpoint_write(
        self,
    ) -> None:
        marker = self.case["routing"]["marker_token"]

        def fail_scores(invocation, *_args, **_kwargs):
            if invocation.phase == "score":
                return AttemptResult(1, "", stderr="scorer failed")
            if invocation.phase == "routing" and invocation.variant == "positive":
                return AttemptResult(0, marker)
            return AttemptResult(0, "fixture answer")

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output = temporary_path / "results"
            source = temporary_path / "airi"
            source.mkdir()
            checkouts = {"control": source, "treatment": source}
            arguments = [
                "--airi-source",
                str(source),
                "--output-dir",
                str(output),
            ]
            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch("scripts.run_forward_eval.prepare_checkouts", return_value=checkouts),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex", side_effect=fail_scores),
            ):
                self.assertEqual(main(arguments), 2)

            manifest = load_json(output / "manifest.json")
            identity = {
                key: manifest[key]
                for key in ("case", "repository", "skill", "profile", "planned_calls")
            }
            identity["profile"] = dict(identity["profile"])
            identity["profile"]["call_timeout_seconds"] = 1800
            write_json(
                output / "partial-manifest.json",
                {
                    "schema_version": 1,
                    "identity": identity,
                    "started_at": manifest["started_at"],
                    "resume_history": [
                        {
                            "previous_call_timeout_seconds": 900,
                            "call_timeout_seconds": 1800,
                        }
                    ],
                },
            )
            checkpoint = next(
                record
                for record in manifest["results"]
                if record["id"] == "routing-positive-ipc-evolution-r1"
            )
            checkpoint["metadata"] = {"sentinel": "newer-partial"}
            checkpoint_path = output / ".checkpoints" / f"{checkpoint['id']}.json"
            write_json(checkpoint_path, checkpoint)

            with (
                mock.patch("scripts.run_forward_eval.codex_version", return_value="0.144.4"),
                mock.patch(
                    "scripts.run_forward_eval.prepare_checkouts", return_value=checkouts
                ),
                mock.patch("scripts.run_forward_eval.assert_clean"),
                mock.patch("scripts.run_forward_eval.run_codex") as run,
            ):
                with self.assertRaisesRegex(EvaluationError, "profile does not match"):
                    main(
                        [
                            *arguments,
                            "--resume",
                            "--call-timeout-seconds",
                            "1200",
                        ]
                    )
                run.assert_not_called()
            self.assertEqual(
                load_json(checkpoint_path)["metadata"], {"sentinel": "newer-partial"}
            )


if __name__ == "__main__":
    unittest.main()
