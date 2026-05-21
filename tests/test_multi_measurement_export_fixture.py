from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "multi_measurement_export"


class MultiMeasurementExportFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "export-input.json",
            FIXTURE / "expected-export-summary.json",
            FIXTURE / "snapshots" / "measurement-1001-parameter-snapshot.json",
            FIXTURE / "snapshots" / "measurement-1002-parameter-snapshot.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_keeps_selected_measurements_as_export_unit(self) -> None:
        summary = json.loads((FIXTURE / "expected-export-summary.json").read_text())
        export_set = summary["selected_export_set"]

        self.assertEqual(export_set["selection_mode"], "multi_measurement")
        self.assertEqual(export_set["selected_legacy_data_ids"], [1001, 1002])
        self.assertEqual(export_set["traversal_policy"], "non_recursive")
        self.assertEqual(
            [measurement["role"] for measurement in summary["measurements"]],
            ["selected_measurement", "selected_measurement"],
        )
        self.assertIn("automatic analysis-DAG inference", summary["decisions_not_earned"])
        self.assertIn("recursive relation traversal", summary["decisions_not_earned"])
        self.assertIn(
            "Run 1001 Rabi source data",
            export_set["default_included_labels"],
        )
        self.assertIn(
            "Session wiring note",
            export_set["included_linked_context_labels"],
        )

    def test_optional_artifact_has_label_and_is_not_in_default_included_paths(self) -> None:
        summary = json.loads((FIXTURE / "expected-export-summary.json").read_text())
        export_set = summary["selected_export_set"]
        linked_context = {item["path"]: item for item in summary["linked_context"]}
        artifact_path = "artifacts/optional-two-measurement-summary.csv"

        self.assertIn(artifact_path, export_set["optional_paths"])
        self.assertNotIn(artifact_path, export_set["default_included_paths"])
        self.assertEqual(linked_context[artifact_path]["kind"], "artifact")
        self.assertEqual(linked_context[artifact_path]["label"], "qA summary candidate")
        self.assertEqual(linked_context[artifact_path]["include_status"], "optional")
        self.assertEqual(linked_context[artifact_path]["authority"], "user_declared")

    def test_expected_openability_matches_fixture_files(self) -> None:
        summary = json.loads((FIXTURE / "expected-export-summary.json").read_text())
        export_set = summary["selected_export_set"]

        for rel_path in export_set["default_included_paths"]:
            with self.subTest(rel_path=rel_path):
                self.assertTrue((FIXTURE / rel_path).exists())

        for rel_path in export_set["optional_paths"]:
            with self.subTest(rel_path=rel_path):
                self.assertTrue((FIXTURE / rel_path).exists())

        for rel_path in export_set["included_linked_context_paths"]:
            with self.subTest(rel_path=rel_path):
                self.assertTrue((FIXTURE / rel_path).exists())

        for rel_path in export_set["missing_paths"]:
            with self.subTest(rel_path=rel_path):
                self.assertFalse((FIXTURE / rel_path).exists())

    def test_review_states_non_recursive_boundary(self) -> None:
        review = (FIXTURE / "expected-export-review.md").read_text(encoding="utf-8")

        self.assertIn("selected measurements: `1001`, `1002`", review)
        self.assertIn("traversal policy: `non_recursive`", review)
        self.assertIn("Session wiring note", review)
        self.assertIn("qA summary candidate", review)
        self.assertIn("optional rather than silently included", review)
        self.assertIn("not claiming a downstream analysis DAG", review)


if __name__ == "__main__":
    unittest.main()
