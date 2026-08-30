import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
CANONICAL_INDEX = RESULTS / "architecture-review-v2.1-canonical.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ScorerEvidenceTest(unittest.TestCase):
    def test_v21_canonical_index_covers_complete_matrix_and_all_attempts(self) -> None:
        index = load_json(CANONICAL_INDEX)
        self.assertEqual(index["schema_version"], 1)

        contract = index["contract"]
        self.assertEqual(
            contract["rubric_sha256"],
            sha256(ROOT / "evals" / "rubrics" / "architecture-review-v2.1.md"),
        )
        self.assertEqual(
            contract["schema_sha256"],
            sha256(
                ROOT / "evals" / "rubrics" / "architecture-review-v2.1.schema.json"
            ),
        )

        cells = index["cells"]
        expected_cells = {
            (case, producer, scorer)
            for case in ("airi-v0.2-baseline", "marktext-v0.2-baseline")
            for producer in (
                "claude-code-ccswitch-deepseek-v4-pro-high",
                "codex-gpt-5.6-luna-max",
            )
            for scorer in (
                "claude-code-ccswitch-deepseek-v4-pro-high",
                "codex-gpt-5.6-luna-max",
            )
        }
        actual_cells = {
            (
                cell["case_id"],
                cell["producer_profile_id"],
                cell["scorer_profile_id"],
            )
            for cell in cells
        }
        self.assertEqual(actual_cells, expected_cells)

        referenced_directories: set[str] = set()
        canonical_directories: set[str] = set()
        for cell in cells:
            canonical = cell["canonical"]
            directory = canonical["result_directory"]
            self.assertNotIn(directory, canonical_directories)
            canonical_directories.add(directory)
            referenced_directories.add(directory)

            result_dir = RESULTS / directory
            manifest_path = result_dir / "manifest.json"
            manifest = load_json(manifest_path)
            summary = load_json(result_dir / "summary.json")
            self.assertEqual(canonical["manifest_sha256"], sha256(manifest_path))
            self.assertTrue(summary["dataset_complete"])
            self.assertEqual(manifest["case"]["id"], cell["case_id"])
            self.assertEqual(
                manifest["profile"]["profile_id"], cell["scorer_profile_id"]
            )
            producer_profile = manifest.get("rescore_source", {}).get(
                "profile_id", manifest["profile"]["profile_id"]
            )
            self.assertEqual(producer_profile, cell["producer_profile_id"])

            for audit in cell["audit_only"]:
                audit_directory = audit["result_directory"]
                self.assertTrue(audit["reason"])
                self.assertNotIn(audit_directory, canonical_directories)
                referenced_directories.add(audit_directory)
                audit_manifest = RESULTS / audit_directory / "manifest.json"
                self.assertEqual(audit["manifest_sha256"], sha256(audit_manifest))

        v21_directories = {
            manifest.parent.name
            for manifest in RESULTS.glob("*v2.1*/manifest.json")
        }
        self.assertEqual(referenced_directories, v21_directories)


if __name__ == "__main__":
    unittest.main()
