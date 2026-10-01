from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.vendor_lib import materialize_package, tree_digest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path("skills/evolve-software-architecture")
ARCHIVE = Path("docs/archive/project-type-adapters/v0.1.2")


class GenericPackageTest(unittest.TestCase):
    def test_archive_is_byte_identical_to_release(self) -> None:
        for name in ("desktop-tauri.md", "project-type-selection.md"):
            with self.subTest(name=name):
                released = subprocess.check_output(
                    ["git", "show", f"v0.1.2:{PACKAGE}/references/project-types/{name}"],
                    cwd=ROOT,
                )
                self.assertEqual((ROOT / ARCHIVE / name).read_bytes(), released)

    def test_candidate_archive_contains_only_installable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "source"
            repo.mkdir()
            shutil.copytree(ROOT / PACKAGE, repo / PACKAGE)
            shutil.copytree(ROOT / ARCHIVE, repo / ARCHIVE)
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Package Test", "-c", "user.email=test@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "test package"],
                cwd=repo, check=True,
            )
            bundle = Path(temporary) / "bundle"
            installed = materialize_package(repo, "HEAD", bundle)
            self.assertEqual(tree_digest(installed), tree_digest(ROOT / PACKAGE))
            self.assertFalse((bundle / "docs").exists())
            self.assertFalse((installed / "references/project-types").exists())
            self.assertTrue((installed / "references/technology-context.md").is_file())

    def test_generic_package_validates_without_archived_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / PACKAGE, root / PACKAGE)
            command = [sys.executable, str(ROOT / "scripts/validate-skill.py"), "--root", str(root)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            (root / PACKAGE / "references/technology-context.md").unlink()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required reference", result.stderr)


if __name__ == "__main__":
    unittest.main()
