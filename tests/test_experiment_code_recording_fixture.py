from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "experiment_code_recording" / "basic_step_code_record"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "code-recording-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-code-recording-summary.json").read_text(encoding="utf-8")
    )


class ExperimentCodeRecordingFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "code-recording-input.json",
            FIXTURE / "expected-code-recording-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_recording_policy_is_explicit_include_not_git_analysis(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]

        self.assertEqual(summary["recording_policy"], source["recording_policy"])
        self.assertEqual(summary["recording_policy"]["mode"], "minimal_explicit_include_recording")
        self.assertEqual(summary["recording_policy"]["internal_git_inspection"], "not_performed")
        self.assertEqual(
            summary["recording_policy"]["default_file_inclusion"],
            "not_recorded_unless_included",
        )
        encoded = json.dumps(summary)
        self.assertNotIn("working_tree_state", encoded)
        self.assertNotIn("nested_repository", encoded)

    def test_recorded_context_records_entrypoint_and_only_included_files(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        context = summary["recorded_code_contexts"][0]
        source_context = source["recorded_code_contexts"][0]

        self.assertEqual(context["entrypoint_path"], "readout_calibration_entrypoint.ipynb")
        self.assertEqual(context["entrypoint_kind"], "notebook")
        self.assertEqual(context["entrypoint_recorded_form"], "source_without_outputs")
        self.assertEqual(context["execution_claim"], "not_executed_by_fixture")
        self.assertEqual(context["included_file_count"], len(source_context["included_files"]))
        self.assertEqual(
            [item["path"] for item in summary["included_files"]],
            [item["path"] for item in source_context["included_files"]],
        )

    def test_notebooks_are_stripped_before_recording(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        notebook_files = [
            item for item in summary["included_files"] if item["path"].endswith(".ipynb")
        ]

        self.assertGreaterEqual(len(notebook_files), 1)
        self.assertEqual(
            {item["recorded_form"] for item in notebook_files},
            {"source_without_outputs"},
        )
        self.assertEqual(
            summary["recording_policy"]["notebook_output_policy"],
            "strip_outputs_before_recording",
        )
        self.assertIn(
            "notebook_outputs_stripped",
            {item["code"] for item in summary["attention"]},
        )

    def test_unrecorded_files_are_policy_not_folder_warnings(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]

        self.assertEqual(
            summary["not_recorded_policy"],
            source["recorded_code_contexts"][0]["not_recorded_policy"],
        )
        self.assertEqual(
            summary["recording_policy"]["directory_scan_policy"],
            "do_not_surface_unrecorded_files_as_warnings",
        )
        self.assertIn(
            "unrecorded_files_not_recorded",
            {item["code"] for item in summary["attention"]},
        )
        encoded = json.dumps(summary)
        self.assertNotIn("backup_variant_visible", encoded)
        self.assertNotIn("dirty_git_observed", encoded)

    def test_calibration_step_references_code_context_as_named_input(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        reference = summary["calibration_step_references"][0]

        self.assertEqual(reference["inputs"], source["calibration_steps"][0]["inputs"])
        self.assertEqual(
            [entry["name"] for entry in reference["inputs"]],
            ["code_context", "parameter_state", "setup_binding"],
        )
        self.assertEqual(
            reference["inputs"][0]["snapshot_id"],
            "code-context-readout-cali-0001",
        )

    def test_no_execution_or_mutation_analysis_is_claimed(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["recorded_code_contexts"][0]["mutation_capability"],
            "not_analyzed",
        )
        self.assertIn("code_execution_not_granted", attention)
        self.assertEqual(
            attention["code_execution_not_granted"]["does_not_claim"],
            "execution_permission",
        )
        self.assertEqual(summary["recording_policy"]["dependency_discovery"], "not_performed")

    def test_captured_version_candidate_is_not_storage_or_workflow_contract(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        candidate = summary["candidate_summary"]["captured_version_candidates"][0]
        source_candidate = source["captured_version_candidates"][0]

        self.assertEqual(candidate["candidate_status"], "candidate_not_committed_contract")
        self.assertEqual(candidate["storage_claim"], "not_decided_by_fixture")
        self.assertEqual(
            candidate["included_files"],
            source_candidate["capture_scope"]["included_files"],
        )
        self.assertEqual(candidate["default_file_inclusion"], "not_recorded_unless_included")
        self.assertIn("workflow DAG", summary["decisions_not_earned"])
        self.assertIn("default record-all file tracking", summary["decisions_not_earned"])

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-code-recording-review.md").read_text(encoding="utf-8")

        self.assertIn("minimal and explicit-include-based", review)
        self.assertIn("does not scan unrecorded files", review)
        self.assertIn("Internal Git state is not inspected", review)
        self.assertIn("Notebook outputs are stripped", review)
        self.assertIn("does not grant execution permission", review)
        self.assertIn("default record-all file tracking", review)


if __name__ == "__main__":
    unittest.main()
