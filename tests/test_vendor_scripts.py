from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "scripts" / "vendor-skill.py"
CHECK = ROOT / "scripts" / "check-vendor-drift.py"
NAME = "evolve-software-architecture"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


class VendorScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.target], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_vendor(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VENDOR), "--target", str(self.target), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=check,
        )

    def test_release_content_and_peeled_commit_are_locked(self) -> None:
        self.run_vendor("--ref", "v0.1.1")
        installed = (
            self.target / ".agents" / "skills" / NAME / "SKILL.md"
        ).read_text(encoding="utf-8")
        released = git("show", f"v0.1.1:skills/{NAME}/SKILL.md")
        self.assertEqual(installed.rstrip(), released.rstrip())
        lock = json.loads(
            (self.target / ".agents" / "vendor-lock.json").read_text(encoding="utf-8")
        )[NAME]
        self.assertEqual(lock["commit"], git("rev-parse", "v0.1.1^{commit}"))

    def test_non_release_ref_is_rejected(self) -> None:
        result = self.run_vendor("--ref", "HEAD", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SemVer tag", result.stderr)

    def test_check_uses_locked_release_not_worktree(self) -> None:
        self.run_vendor("--ref", "v0.1.1")
        result = subprocess.run(
            [sys.executable, str(CHECK), "--target", str(self.target)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("vendor copy matches v0.1.1", result.stdout)

    def test_update_refuses_local_vendor_changes(self) -> None:
        self.run_vendor("--ref", "v0.1.1")
        skill_md = self.target / ".agents" / "skills" / NAME / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nlocal change\n")
        result = self.run_vendor("--update", "--ref", "v0.1.1", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)

    def test_legacy_tag_object_lock_is_migrated(self) -> None:
        self.run_vendor("--ref", "v0.1.1")
        lock_path = self.target / ".agents" / "vendor-lock.json"
        locks = json.loads(lock_path.read_text(encoding="utf-8"))
        locks[NAME]["commit"] = git("rev-parse", "v0.1.1")
        lock_path.write_text(json.dumps(locks, indent=2) + "\n", encoding="utf-8")
        self.run_vendor("--update", "--ref", "v0.1.1")
        migrated = json.loads(lock_path.read_text(encoding="utf-8"))[NAME]
        self.assertEqual(migrated["commit"], git("rev-parse", "v0.1.1^{commit}"))


if __name__ == "__main__":
    unittest.main()
