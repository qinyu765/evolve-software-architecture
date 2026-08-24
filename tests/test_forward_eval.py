from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_forward_eval import (
    AttemptResult,
    Invocation,
    aggregate_results,
    assert_control_uncontaminated,
    build_invocation_matrix,
    case_digest,
    claude_command,
    execute_with_retry,
    frontmatter_bytes,
    inject_routing_marker,
    load_json,
    main,
    parse_claude_output,
    redact_text,
    run_case_groups,
    scorer_prompt,
    skill_parent,
    summary_markdown,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "evals" / "cases" / "airi-v0.2.json"


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

    def test_failed_case_stops_later_repetitions(self) -> None:
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
        self.assertEqual(len(results), 1)
        self.assertEqual(checkpointed, ["case-r1"])
        self.assertEqual(skipped, ["case-r2", "case-r3"])

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


if __name__ == "__main__":
    unittest.main()
