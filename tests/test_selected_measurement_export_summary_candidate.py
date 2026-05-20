from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.selected_measurement_export import (
    build_selected_measurement_export_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "preview_ready_measurement_export"


def _load_input() -> dict:
    return json.loads((FIXTURE / "export-input.json").read_text(encoding="utf-8"))


class SelectedMeasurementExportSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_selected_measurement_export_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_only_selected_measurements_are_summarized(self) -> None:
        source = _load_input()
        unselected = copy.deepcopy(source["measurements"][0])
        unselected["legacy_data_id"] = 9999
        unselected["export_source"] = "LAB_LOCAL:/redacted/unselected.csv"
        source["measurements"].append(unselected)

        summary = build_selected_measurement_export_summary(source)

        self.assertEqual(
            [measurement["legacy_data_id"] for measurement in summary["measurements"]],
            [1001, 1002],
        )

    def test_linked_context_is_filtered_to_selected_measurements(self) -> None:
        source = _load_input()
        source["linked_context"].append(
            {
                "kind": "attachment",
                "label": "Unselected note",
                "path": "attachments/unselected-note.md",
                "include_status": "included_by_user",
                "relation": "documents",
                "authority": "user_declared",
                "linked_legacy_data_ids": [9999],
            }
        )

        summary = build_selected_measurement_export_summary(source)

        self.assertNotIn(
            "attachments/unselected-note.md",
            [item["path"] for item in summary["linked_context"]],
        )

    def test_degraded_preview_does_not_infer_from_source_header(self) -> None:
        summary = build_selected_measurement_export_summary(_load_input())
        measurements = {
            measurement["legacy_data_id"]: measurement for measurement in summary["measurements"]
        }

        self.assertEqual(measurements[1002]["preview"]["status"], "degraded_preview")
        self.assertEqual(measurements[1002]["preview"]["declared_roles"], [])
        self.assertEqual(measurements[1002]["preview"]["plot_candidates"], [])
        self.assertEqual(
            measurements[1002]["preview"]["warnings"][0]["code"],
            "preview_metadata_missing",
        )

    def test_primary_data_path_must_match_source_file(self) -> None:
        source = _load_input()
        source["measurements"][0]["default_bundle"][0]["path"] = "source/session-alpha/wrong.csv"

        with self.assertRaisesRegex(ValueError, "primary_data path"):
            build_selected_measurement_export_summary(source)

    def test_plot_candidate_source_must_match_source_file(self) -> None:
        source = _load_input()
        source["measurements"][0]["preview_metadata"]["plot_candidates"][0]["source"] = (
            "source/session-alpha/wrong.csv"
        )

        with self.assertRaisesRegex(ValueError, "plot candidate source"):
            build_selected_measurement_export_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_selected_measurement_export_summary(source)

        source["measurements"][0]["default_bundle"][0]["label"] = "mutated"
        source["measurements"][0]["preview_metadata"]["declared_columns"][0]["label"] = "mutated"

        measurement = summary["measurements"][0]
        self.assertEqual(measurement["default_bundle"][0]["label"], "Run 1001 Rabi source data")
        self.assertEqual(measurement["preview"]["declared_roles"][0]["label"], "Drive amplitude")

    def test_warning_codes_are_derived_for_all_present_cases(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["linked_context"][2])
        duplicate["label"] = "Run 1001 missing setup note"
        duplicate["path"] = "attachments/run-01001-missing-setup.md"
        duplicate["linked_legacy_data_ids"] = [1001]
        source["linked_context"].append(duplicate)

        summary = build_selected_measurement_export_summary(source)

        self.assertEqual(
            [
                warning["subject"]
                for warning in summary["warnings"]
                if warning["code"] == "missing_companion"
            ],
            [
                "attachments/run-01002-fit-note.md",
                "attachments/run-01001-missing-setup.md",
            ],
        )

    def test_normal_policy_and_boundary_disclaimers_are_not_warnings(self) -> None:
        summary = build_selected_measurement_export_summary(_load_input())
        warning_codes = [warning["code"] for warning in summary["warnings"]]

        self.assertNotIn("no_silent_transform", warning_codes)
        self.assertNotIn("visible_optional_link_excluded", warning_codes)
        self.assertNotIn("non_recursive_traversal", warning_codes)
        self.assertNotIn("not_scientific_validation", warning_codes)


if __name__ == "__main__":
    unittest.main()
