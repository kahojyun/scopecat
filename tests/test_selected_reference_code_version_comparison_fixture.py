from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "code_version_context_compare"
)


def _input_fixture() -> dict:
    return json.loads(
        (FIXTURE / "reference-code-comparison-input.json").read_text(encoding="utf-8")
    )


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-reference-code-comparison-summary.json").read_text(encoding="utf-8")
    )


def _contexts_by_side(source: dict) -> dict:
    return {item["side"]: item for item in source["recorded_code_contexts"]}


def _files_by_path(context: dict) -> dict:
    return {item["path"]: item for item in context["included_files"]}


class SelectedReferenceCodeVersionComparisonFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "reference-code-comparison-input.json",
            FIXTURE / "expected-reference-code-comparison-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_code_version_scope_moves_out_of_not_compared_without_runtime_claims(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]

        self.assertIn("recorded_code_context", source["comparison_request"]["comparison_scope"])
        self.assertIn(
            "captured_code_version_record_identity",
            source["comparison_request"]["comparison_scope"],
        )
        self.assertNotIn("experiment_code_version", summary["not_compared_scope"])
        self.assertEqual(
            summary["not_compared_scope"],
            source["comparison_request"]["not_compared_scope"],
        )

    def test_measurements_reference_recorded_code_context_as_named_input(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        source_inputs = {
            measurement["side"]: {
                item["name"]: item["snapshot_id"] for item in measurement["inputs"]
            }
            for measurement in source["measurements"]
        }
        summary_contexts = {
            item["side"]: item["context_id"] for item in summary["code_context_pair"]
        }

        self.assertEqual(
            source_inputs["reference"]["code_context"],
            "code-context-readout-cali-0001",
        )
        self.assertEqual(
            source_inputs["current"]["code_context"],
            "code-context-readout-cali-0002",
        )
        self.assertEqual(summary_contexts["reference"], source_inputs["reference"]["code_context"])
        self.assertEqual(summary_contexts["current"], source_inputs["current"]["code_context"])

    def test_entrypoint_can_match_while_source_observation_changes(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        source_contexts = _contexts_by_side(source)
        comparison = summary["code_context_comparison"]
        summary_contexts = {item["side"]: item for item in summary["code_context_pair"]}
        inventory = {item["path"]: item for item in summary["file_inventory_comparison"]}
        reference_entrypoint = source_contexts["reference"]["entrypoint_path"]
        current_entrypoint = source_contexts["current"]["entrypoint_path"]
        reference_files = _files_by_path(source_contexts["reference"])
        current_files = _files_by_path(source_contexts["current"])

        self.assertEqual(reference_entrypoint, current_entrypoint)
        self.assertEqual(summary_contexts["reference"]["entrypoint_path"], reference_entrypoint)
        self.assertEqual(summary_contexts["current"]["entrypoint_path"], current_entrypoint)
        self.assertEqual(
            summary_contexts["reference"]["entrypoint_recorded_form"],
            source_contexts["reference"]["entrypoint_recorded_form"],
        )
        self.assertEqual(
            summary_contexts["current"]["entrypoint_recorded_form"],
            source_contexts["current"]["entrypoint_recorded_form"],
        )
        self.assertEqual(comparison["entrypoint_path_finding"], "same_observed")
        self.assertEqual(
            comparison["entrypoint_recorded_form_finding"],
            "same_observed",
        )
        self.assertEqual(
            inventory[reference_entrypoint]["reference_observation_id"],
            reference_files[reference_entrypoint]["recorded_source_observation_id"],
        )
        self.assertEqual(
            inventory[current_entrypoint]["current_observation_id"],
            current_files[current_entrypoint]["recorded_source_observation_id"],
        )
        self.assertEqual(
            inventory["readout_calibration_entrypoint.ipynb"]["finding"],
            "changed",
        )

    def test_inclusion_inventory_distinguishes_same_observed_and_missing_helpers(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        source_contexts = _contexts_by_side(source)
        reference_files = _files_by_path(source_contexts["reference"])
        current_files = _files_by_path(source_contexts["current"])
        inventory = {item["path"]: item for item in summary["file_inventory_comparison"]}
        inventory_paths = set(inventory)

        self.assertEqual(inventory_paths, set(reference_files) | set(current_files))
        self.assertEqual(
            inventory["helpers/record_measurement_context.py"]["reference_observation_id"],
            reference_files["helpers/record_measurement_context.py"][
                "recorded_source_observation_id"
            ],
        )
        self.assertEqual(
            inventory["helpers/record_measurement_context.py"]["current_observation_id"],
            current_files["helpers/record_measurement_context.py"][
                "recorded_source_observation_id"
            ],
        )
        self.assertEqual(
            inventory["helpers/record_measurement_context.py"]["finding"],
            "same_observed",
        )
        self.assertEqual(
            inventory["helpers/readout_correction.py"]["reference_observation_id"],
            reference_files["helpers/readout_correction.py"]["recorded_source_observation_id"],
        )
        self.assertIsNone(inventory["helpers/readout_correction.py"]["current_observation_id"])
        self.assertEqual(
            inventory["helpers/readout_correction.py"]["finding"],
            "missing_on_current",
        )
        self.assertIsNone(inventory["helpers/readout_correction_v2.py"]["reference_observation_id"])
        self.assertEqual(
            inventory["helpers/readout_correction_v2.py"]["current_observation_id"],
            current_files["helpers/readout_correction_v2.py"]["recorded_source_observation_id"],
        )
        self.assertEqual(
            inventory["helpers/readout_correction_v2.py"]["finding"],
            "missing_on_reference",
        )

    def test_findings_reuse_precise_vocabulary_not_git_diff_language(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        findings = summary["findings"]

        self.assertEqual(source["expected_finding_codes"], [item["code"] for item in findings])
        self.assertEqual(
            {item["kind"] for item in findings},
            {"changed", "missing", "redacted", "same_observed"},
        )
        encoded = json.dumps(summary).lower()
        self.assertNotIn("git diff", encoded)
        self.assertNotIn("dirty", encoded)
        self.assertNotIn("dependency resolved", encoded)

    def test_recorded_source_observation_ids_are_not_integrity_contract(self) -> None:
        summary = _expected_summary()

        self.assertIn(
            "fixture-level comparison tokens",
            summary["reference_semantics"]["recorded_source_observation"],
        )
        self.assertIn("checksum or archive integrity contract", summary["decisions_not_earned"])
        self.assertIn("content-addressed storage", summary["boundary_notes"][2])

    def test_no_execution_restore_or_environment_readiness_is_claimed(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        contexts = source["recorded_code_contexts"]

        self.assertEqual(
            {item["execution_claim"] for item in contexts},
            {"not_executed_by_fixture"},
        )
        self.assertEqual(
            {item["recording_policy"]["internal_git_inspection"] for item in contexts},
            {"not_performed"},
        )
        self.assertIn("environment_readiness", summary["candidate_summary"]["not_compared_scope"])
        self.assertIn("selected-version loading", summary["decisions_not_earned"])
        self.assertIn("code execution", summary["decisions_not_earned"])

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-reference-code-comparison-review.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("changed recorded-code-context finding", review)
        self.assertIn("record notebooks as source without outputs", review)
        self.assertIn("Environment readiness is not compared", review)
        self.assertIn("does not inspect", review)
        self.assertIn("internal Git state", review)
        self.assertIn("Recorded source observation IDs are fixture-level", review)


if __name__ == "__main__":
    unittest.main()
