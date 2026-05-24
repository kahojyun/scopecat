from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.selected_reference_comparison import (
    build_selected_reference_code_context_summary,
    build_selected_reference_context_summary,
)

ROOT = Path(__file__).resolve().parents[1]
BASIC_FIXTURE = (
    ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "basic_context_compare"
)
CODE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "code_context_compare"
)

BASIC_FINDING_CODES = [
    "same_observed_preview_shape",
    "same_observed_setup_binding",
    "changed_parameter_state",
    "missing_current_fit_summary",
    "unlinked_reference_analysis_note",
    "unverified_mounted_sample_identity",
    "redacted_station_connection_details",
]

CODE_FINDING_CODES = [
    "changed_recorded_code_context",
    "changed_code_snapshot_record_identity",
    "same_observed_code_entrypoint",
    "same_observed_notebook_recording_policy",
    "changed_entrypoint_source_observation",
    "same_observed_helper_source_observation",
    "missing_current_readout_correction_helper",
    "missing_reference_readout_correction_v2_helper",
    "same_observed_declared_environment_ref",
    "redacted_external_code_root",
]


def _load_basic_input() -> dict:
    return json.loads(
        (BASIC_FIXTURE / "reference-comparison-input.json").read_text(encoding="utf-8")
    )


def _load_basic_expected() -> dict:
    return json.loads(
        (BASIC_FIXTURE / "expected-reference-comparison-summary.json").read_text(encoding="utf-8")
    )


def _load_code_input() -> dict:
    return json.loads(
        (CODE_FIXTURE / "reference-code-comparison-input.json").read_text(encoding="utf-8")
    )


def _load_code_expected() -> dict:
    return json.loads(
        (CODE_FIXTURE / "expected-reference-code-comparison-summary.json").read_text(
            encoding="utf-8"
        )
    )


class SelectedReferenceComparisonSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_basic_context_summary(self) -> None:
        summary = build_selected_reference_context_summary(_load_basic_input())
        expected = _load_basic_expected()["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_basic_context_reports_precise_findings_without_user_judgment(self) -> None:
        summary = build_selected_reference_context_summary(_load_basic_input())
        findings = {item["code"]: item for item in summary["findings"]}

        self.assertEqual([item["code"] for item in summary["findings"]], BASIC_FINDING_CODES)
        self.assertEqual(findings["changed_parameter_state"]["kind"], "changed")
        self.assertEqual(findings["same_observed_setup_binding"]["kind"], "same_observed")
        self.assertEqual(findings["missing_current_fit_summary"]["kind"], "missing")
        self.assertEqual(findings["unlinked_reference_analysis_note"]["kind"], "unlinked")
        self.assertEqual(findings["unverified_mounted_sample_identity"]["kind"], "unverified")
        self.assertEqual(findings["redacted_station_connection_details"]["kind"], "redacted")
        self.assertIn("fit_quality", summary["not_compared_scope"])
        self.assertIn("user_interpretation", summary["not_compared_scope"])
        self.assertEqual(summary["warnings"], [])

    def test_basic_context_declared_facts_are_explicit_scope(self) -> None:
        source = _load_basic_input()

        self.assertIn("declared_facts", source["comparison_request"]["comparison_scope"])
        self.assertIn(
            "unverified_mounted_sample_identity",
            [item["code"] for item in build_selected_reference_context_summary(source)["findings"]],
        )

    def test_basic_context_rejects_missing_declared_facts_scope(self) -> None:
        source = _load_basic_input()
        source["comparison_request"]["comparison_scope"].remove("declared_facts")

        with self.assertRaisesRegex(ValueError, "comparison scope"):
            build_selected_reference_context_summary(source)

    def test_basic_context_rejects_code_context_inputs(self) -> None:
        source = _load_basic_input()
        for measurement in source["measurements"]:
            measurement["inputs"].append(
                {
                    "name": "code_context",
                    "snapshot_id": "code-context-out-of-scope",
                    "role": "recorded_entrypoint_and_included_files",
                }
            )

        with self.assertRaisesRegex(ValueError, "must not compare code context"):
            build_selected_reference_context_summary(source)

    def test_basic_context_primary_data_references_match_sides(self) -> None:
        source = _load_basic_input()
        measurements = {item["side"]: item for item in source["measurements"]}

        self.assertEqual(
            measurements["reference"]["primary_data_reference"],
            "source/reference-compare-reference/chevron-reference-source.csv",
        )
        self.assertEqual(
            measurements["current"]["primary_data_reference"],
            "source/reference-compare-current/chevron-current-source.csv",
        )

    def test_redacted_declared_fact_value_must_stay_redacted(self) -> None:
        source = _load_basic_input()
        facts = {item["fact_id"]: item for item in source["declared_facts"]}

        self.assertEqual(facts["station-connection-detail"]["value"], "redacted")

        facts["station-connection-detail"]["value"] = "rack-7-slot-3"
        with self.assertRaisesRegex(ValueError, "declared fact value must stay redacted"):
            build_selected_reference_context_summary(source)

    def test_basic_context_rejects_scope_expansion(self) -> None:
        source = _load_basic_input()
        source["comparison_request"]["comparison_scope"].append("raw_data_comparison")

        with self.assertRaisesRegex(ValueError, "comparison scope"):
            build_selected_reference_context_summary(source)

    def test_basic_context_rejects_special_reference_selection_semantics(self) -> None:
        source = _load_basic_input()
        source["comparison_request"]["reference_selection"]["selection_source"] = (
            "scopecat_reference_engine"
        )

        with self.assertRaisesRegex(ValueError, "ordinary measurement marks"):
            build_selected_reference_context_summary(source)

    def test_basic_context_expected_codes_are_not_builder_input(self) -> None:
        source = _load_basic_input()
        source["expected_finding_codes"] = []

        self.assertEqual(
            [item["code"] for item in build_selected_reference_context_summary(source)["findings"]],
            BASIC_FINDING_CODES,
        )

    def test_basic_context_emitted_ids_must_stay_public_safe(self) -> None:
        source = _load_basic_input()
        source["measurements"][0]["measurement_id"] = "/Users/lab/private/measurement"
        source["comparison_request"]["reference_measurement_id"] = "/Users/lab/private/measurement"

        with self.assertRaisesRegex(ValueError, "measurement id must be public-safe"):
            build_selected_reference_context_summary(source)

        source = _load_basic_input()
        source["measurements"][0]["sample_id"] = "private-sample-alpha"

        with self.assertRaisesRegex(ValueError, "sample id must be public-safe"):
            build_selected_reference_context_summary(source)

        source = _load_basic_input()
        source["measurements"][0]["inputs"][0]["snapshot_id"] = "private-param-state"

        with self.assertRaisesRegex(ValueError, "snapshot id must be public-safe"):
            build_selected_reference_context_summary(source)

    def test_basic_context_snapshot_summaries_are_required_and_unique(self) -> None:
        source = _load_basic_input()
        source["snapshot_summaries"] = source["snapshot_summaries"][1:]

        with self.assertRaisesRegex(ValueError, "missing snapshot summary"):
            build_selected_reference_context_summary(source)

        source = _load_basic_input()
        source["snapshot_summaries"].append(copy.deepcopy(source["snapshot_summaries"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            build_selected_reference_context_summary(source)

    def test_basic_context_output_does_not_alias_input_objects(self) -> None:
        source = _load_basic_input()
        summary = build_selected_reference_context_summary(source)

        source["comparison_request"]["not_compared_scope"][0] = "mutated"
        source["measurements"][0]["declared_preview_metadata"]["axis_order"][0] = "mutated"

        self.assertEqual(summary["not_compared_scope"][0], "fit_quality")
        self.assertEqual(
            summary["preview_comparison"]["axis_order"],
            ["coupler_bias_v", "drive_duration_ns"],
        )

    def test_builds_expected_code_context_summary(self) -> None:
        summary = build_selected_reference_code_context_summary(_load_code_input())
        expected = _load_code_expected()["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_code_context_reports_recorded_code_findings_without_runtime_claims(self) -> None:
        summary = build_selected_reference_code_context_summary(_load_code_input())
        findings = {item["code"]: item for item in summary["findings"]}
        inventory = {item["path"]: item for item in summary["file_inventory_comparison"]}

        self.assertEqual([item["code"] for item in summary["findings"]], CODE_FINDING_CODES)
        self.assertEqual(findings["changed_recorded_code_context"]["kind"], "changed")
        self.assertEqual(findings["changed_code_snapshot_record_identity"]["kind"], "changed")
        self.assertEqual(findings["same_observed_code_entrypoint"]["kind"], "same_observed")
        self.assertEqual(findings["redacted_external_code_root"]["kind"], "redacted")
        self.assertEqual(
            inventory["helpers/readout_correction.py"]["finding"],
            "missing_on_current",
        )
        self.assertEqual(
            inventory["helpers/readout_correction_v2.py"]["finding"],
            "missing_on_reference",
        )
        self.assertEqual(summary["code_context_comparison"]["execution_finding"], "not_compared")
        self.assertIn("environment_readiness", summary["not_compared_scope"])
        self.assertIn("code_execution", summary["not_compared_scope"])

    def test_code_context_fixture_only_uses_code_context_inputs(self) -> None:
        for measurement in _load_code_input()["measurements"]:
            self.assertEqual(
                [item["name"] for item in measurement["inputs"]],
                ["code_context"],
            )

    def test_code_context_expected_codes_are_not_builder_input(self) -> None:
        source = _load_code_input()
        source["expected_finding_codes"] = []

        self.assertEqual(
            [
                item["code"]
                for item in build_selected_reference_code_context_summary(source)["findings"]
            ],
            CODE_FINDING_CODES,
        )

    def test_code_context_fixture_expected_codes_match_candidate_output(self) -> None:
        source = _load_code_input()

        self.assertEqual(source["expected_finding_codes"], CODE_FINDING_CODES)
        self.assertEqual(
            [
                item["code"]
                for item in build_selected_reference_code_context_summary(source)["findings"]
            ],
            source["expected_finding_codes"],
        )

    def test_code_context_rejects_git_or_dependency_boundary_expansion(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["recording_policy"]["internal_git_inspection"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "recording policy"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_external_root_display_must_stay_public_safe(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][1]["external_root_display"] = "/Users/lab/private/readout"

        with self.assertRaisesRegex(ValueError, "public-safe and redacted"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_emitted_ids_must_stay_public_safe(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["external_root_id"] = "/Users/lab/private/control"

        with self.assertRaisesRegex(ValueError, "external root id must be public-safe"):
            build_selected_reference_code_context_summary(source)

        source = _load_code_input()
        source["recorded_code_contexts"][0]["included_files"][0][
            "recorded_source_observation_id"
        ] = "private-source-observation"

        with self.assertRaisesRegex(
            ValueError, "recorded source observation id must be public-safe"
        ):
            build_selected_reference_code_context_summary(source)

        source = _load_code_input()
        source["recorded_code_contexts"][0]["declared_context_refs"][0]["ref_id"] = (
            "private-env-profile"
        )

        with self.assertRaisesRegex(ValueError, "declared context ref id must be public-safe"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_rejects_non_code_inputs(self) -> None:
        source = _load_code_input()
        source["measurements"][0]["inputs"].append(
            {
                "name": "parameter_state",
                "snapshot_id": "param-state-0003",
                "role": "selected_calibration_values",
            }
        )

        with self.assertRaisesRegex(ValueError, "only reference code_context"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_paths_must_be_relative(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["entrypoint_path"] = "/tmp/entrypoint.ipynb"

        with self.assertRaisesRegex(ValueError, "entrypoint path must be relative"):
            build_selected_reference_code_context_summary(source)

        source = _load_code_input()
        source["recorded_code_contexts"][0]["included_files"][0]["path"] = "helpers\\private.py"

        with self.assertRaisesRegex(ValueError, "included file path must be relative"):
            build_selected_reference_code_context_summary(source)

        source = _load_code_input()
        source["recorded_code_contexts"][0]["included_files"][0]["path"] = "../private.py"

        with self.assertRaisesRegex(ValueError, "included file path must be relative"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_entrypoint_must_be_included(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["entrypoint_path"] = "missing-entrypoint.ipynb"

        with self.assertRaisesRegex(ValueError, "entrypoint must be included"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_requires_environment_profile_hint(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["declared_context_refs"] = []

        with self.assertRaisesRegex(ValueError, "environment profile hint"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_rejects_execution_claims(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["execution_claim"] = "executed_by_fixture"

        with self.assertRaisesRegex(ValueError, "must not claim execution"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_requires_notebook_source_without_outputs(self) -> None:
        source = _load_code_input()
        source["recorded_code_contexts"][0]["entrypoint_kind"] = "script"

        with self.assertRaisesRegex(ValueError, "entrypoint kind must be notebook"):
            build_selected_reference_code_context_summary(source)

        source = _load_code_input()
        source["recorded_code_contexts"][0]["entrypoint_recorded_form"] = "source_with_outputs"

        with self.assertRaisesRegex(ValueError, "source without outputs"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_declared_ref_comparison_is_order_independent(self) -> None:
        source = _load_code_input()
        for context in source["recorded_code_contexts"]:
            context["declared_context_refs"].append(
                {
                    "ref_id": f"analysis-profile-{context['side']}",
                    "ref_kind": "analysis_profile_hint",
                    "authority": "user_declared",
                }
            )
        source["recorded_code_contexts"][1]["declared_context_refs"].reverse()

        summary = build_selected_reference_code_context_summary(source)

        self.assertEqual(
            summary["code_context_comparison"]["declared_context_ref_finding"],
            "changed",
        )

        source["recorded_code_contexts"][1]["declared_context_refs"][0]["ref_id"] = (
            "analysis-profile-reference"
        )
        summary = build_selected_reference_code_context_summary(source)

        self.assertEqual(
            summary["code_context_comparison"]["declared_context_ref_finding"],
            "same_observed",
        )

    def test_code_context_requires_measurements_to_reference_code_contexts(self) -> None:
        source = _load_code_input()
        source["measurements"][0]["inputs"][0]["snapshot_id"] = "missing-code-context"

        with self.assertRaisesRegex(ValueError, "measurement code input"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_output_does_not_alias_input_objects(self) -> None:
        source = _load_code_input()
        summary = build_selected_reference_code_context_summary(source)

        source["comparison_request"]["not_compared_scope"][0] = "mutated"
        source["recorded_code_contexts"][0]["included_files"][0][
            "recorded_source_observation_id"
        ] = "mutated"

        self.assertEqual(summary["not_compared_scope"][0], "internal_git_state")
        self.assertEqual(
            summary["file_inventory_comparison"][0]["reference_observation_id"],
            "source-observation-entrypoint-a",
        )

    def test_duplicate_measurement_sides_are_rejected(self) -> None:
        source = _load_basic_input()
        duplicate = copy.deepcopy(source["measurements"][0])
        source["measurements"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate side"):
            build_selected_reference_context_summary(source)


if __name__ == "__main__":
    unittest.main()
