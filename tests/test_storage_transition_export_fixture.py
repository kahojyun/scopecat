from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "storage_transition_export"


class StorageTransitionExportFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "export-input.json",
            FIXTURE / "expected-export-summary.json",
            FIXTURE / "snapshots" / "run-02001-parameters.json",
            FIXTURE / "snapshots" / "run-02002-parameters.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_distinguishes_identity_reference_and_materialization(self) -> None:
        summary = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )
        measurements = {
            item["measurement_id"]: item
            for item in summary["candidate_summary"]["measurements"]
        }

        managed = measurements["measurement-02001"]
        external = measurements["measurement-02002"]

        self.assertEqual(managed["source_identity"]["kind"], "scopecat_managed_record")
        self.assertEqual(managed["storage_reference"]["mode"], "managed")
        self.assertTrue(managed["storage_reference"]["current_reference"].startswith("scopecat://"))
        self.assertNotEqual(
            managed["storage_reference"]["current_reference"],
            managed["storage_reference"]["package_materialized_path"],
        )

        self.assertEqual(external["source_identity"]["kind"], "external_file_reference")
        self.assertEqual(external["storage_reference"]["mode"], "external_reference")
        self.assertTrue(external["storage_reference"]["current_reference"].startswith("LAB_LOCAL:"))
        self.assertNotEqual(
            external["storage_reference"]["current_reference"],
            external["storage_reference"]["package_materialized_path"],
        )

    def test_available_materialized_paths_exist_and_missing_external_path_does_not(self) -> None:
        summary = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        package_paths: list[str] = []
        for measurement in summary["measurements"]:
            package_paths.append(measurement["storage_reference"]["package_materialized_path"])
            package_paths.extend(item["path"] for item in measurement["default_bundle"])

        linked_context = summary["linked_context"]
        package_paths.extend(
            item["storage_reference"]["package_materialized_path"]
            for item in linked_context
            if item["storage_reference"]["package_materialized_path"] is not None
        )

        for rel_path in package_paths:
            with self.subTest(rel_path=rel_path):
                self.assertTrue((FIXTURE / rel_path).exists())

        missing = next(
            item
            for item in linked_context
            if item["include_status"] == "missing_external_reference"
        )
        self.assertIsNone(missing["storage_reference"]["package_materialized_path"])
        self.assertFalse((FIXTURE / missing["path"]).exists())

    def test_missing_external_reference_is_warning_but_available_external_source_is_not(self) -> None:
        summary = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]
        warnings = summary["warnings"]

        self.assertEqual([warning["code"] for warning in warnings], ["missing_external_reference"])
        self.assertEqual(warnings[0]["subject"], "artifacts/local-fit-scratchpad.ipynb")

        warning_text = json.dumps(warnings)
        self.assertNotIn("02002_qB_ramsey_20260519_095500.csv", warning_text)

    def test_review_states_storage_transition_boundary(self) -> None:
        review = (FIXTURE / "expected-export-review.md").read_text(encoding="utf-8")

        self.assertIn("Managed storage, external source identity, and package materialization", review)
        self.assertIn("package paths are not durable identity", review)
        self.assertIn("temporary", review)
        self.assertIn("normal long-term workflow", review)
        self.assertIn("does not add an importer, package writer, checksum contract", review)

    def test_decisions_not_earned_include_storage_and_package_contracts(self) -> None:
        summary = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )

        self.assertIn("final storage architecture", summary["decisions_not_earned"])
        self.assertIn("final external-reference policy", summary["decisions_not_earned"])
        self.assertIn("package writer or importer behavior", summary["decisions_not_earned"])
        self.assertIn("checksum or archive integrity contract", summary["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
