from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_acceptance import ROOT, run_task


class AcceptanceCaptureTest(unittest.TestCase):
    def test_capture_redacts_paths_and_retains_read_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", source], check=True)
            (source / "README.md").write_text("Synthetic capture source, not a behavior evaluation.\n")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Capture Test", "-c", "user.email=test@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "test capture"],
                cwd=source, check=True,
            )
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
            candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            output = root / "result"
            (output / "answers").mkdir(parents=True)
            (output / "records").mkdir()
            args = argparse.Namespace(phase="answers", model="test-only", effort="high", timeout=10, output_dir=output)
            task = {"id": "capture-only", "kind": "behavior", "repository": "click", "prompt": "test capture"}
            sources = {"click": {"path": source, "commit": commit}}
            original_run = subprocess.run

            def fake_model(command, **kwargs):
                if command[0] != "codex":
                    return original_run(command, **kwargs)
                last = Path(command[command.index("--output-last-message") + 1])
                last.write_text(f"Observed repository: {last.parent}/repository\n")
                event = {"type": "item.completed", "item": {
                    "type": "command_execution", "command": f"cat {last.parent}/repository/README.md",
                    "aggregated_output": "source", "exit_code": 0,
                }}
                return subprocess.CompletedProcess(command, 0, json.dumps(event) + "\n", "")

            with patch("scripts.run_acceptance.subprocess.run", side_effect=fake_model):
                record = run_task(task, args, sources, candidate, [], "")
            self.assertTrue(record["capture_success"])
            self.assertEqual(len(record["read_commands"]), 1)
            saved = (output / "answers/capture-only.md").read_text()
            self.assertNotIn("architecture-acceptance-", saved)
            self.assertNotIn("architecture-acceptance-", record["read_commands"][0]["command"])
            self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True), "")


if __name__ == "__main__":
    unittest.main()
