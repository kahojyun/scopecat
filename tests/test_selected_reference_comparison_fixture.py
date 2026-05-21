from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "basic_context_compare"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "reference-comparison-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-reference-comparison-summary.json").read_text(encoding="utf-8")
    )


class SelectedReferenceComparisonFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "reference-comparison-input.json",
            FIXTURE / "expected-reference-comparison-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_reference_is_selected_context_not_known_good(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        selection = source["comparison_request"]["reference_selection"]
        comparison = summary["comparison"]

        self.assertEqual(
            selection["selection_source"],
            comparison["reference_selection_source"],
        )
        self.assertEqual(selection["mark_label"], comparison["reference_mark_label"])
        self.assertEqual(comparison["known_good_claim"], "not_claimed")
        self.assertEqual(comparison["scientific_comparability_claim"], "not_claimed")
        self.assertIn("ordinary measurement marks", _expected_summary()["boundary_notes"][0])

    def test_named_input_comparison_keeps_context_families_separate(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        comparisons = {item["name"]: item for item in summary["input_comparison"]}

        self.assertEqual(set(comparisons), {"parameter_state", "setup_binding", "station_registry"})
        self.assertEqual(comparisons["parameter_state"]["finding"], "changed")
        self.assertEqual(comparisons["setup_binding"]["finding"], "same_observed")
        self.assertEqual(comparisons["station_registry"]["finding"], "same_observed_redacted")
        self.assertEqual(
            comparisons["parameter_state"]["reference_snapshot_id"],
            "param-state-0002",
        )
        self.assertEqual(
            comparisons["parameter_state"]["current_snapshot_id"],
            "param-state-0003",
        )

    def test_declared_preview_metadata_matches_for_inspection_not_equivalence(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        preview = summary["preview_comparison"]
        measurements = {item["side"]: item for item in source["measurements"]}

        self.assertEqual(preview["finding"], "same_observed")
        self.assertEqual(preview["future_preview_use"], "quick_multi_measurement_browsing")
        self.assertEqual(
            measurements["reference"]["declared_preview_metadata"],
            measurements["current"]["declared_preview_metadata"],
        )
        self.assertEqual(preview["axis_order"], ["coupler_bias_v", "drive_duration_ns"])
        self.assertIn("publication-grade plotting", _expected_summary()["boundary_notes"][2])

    def test_findings_use_precise_vocabulary_not_gap(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        findings = summary["findings"]

        self.assertEqual(source["expected_finding_codes"], [item["code"] for item in findings])
        self.assertEqual(
            {item["kind"] for item in findings},
            {
                "changed",
                "missing",
                "not_compared",
                "redacted",
                "same_observed",
                "unlinked",
                "unverified",
            },
        )
        self.assertNotIn("gap", json.dumps(summary).lower())

    def test_missing_redacted_unverified_and_unlinked_are_distinct(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        findings = {item["code"]: item for item in summary["findings"]}

        self.assertEqual(findings["missing_current_fit_summary"]["kind"], "missing")
        self.assertEqual(findings["redacted_station_connection_details"]["kind"], "redacted")
        self.assertEqual(findings["unverified_mounted_sample_identity"]["kind"], "unverified")
        self.assertEqual(findings["unlinked_reference_analysis_note"]["kind"], "unlinked")

    def test_scientific_equivalence_is_not_compared(self) -> None:
        summary = _expected_summary()
        candidate = summary["candidate_summary"]
        finding = {item["code"]: item for item in candidate["findings"]}[
            "not_compared_scientific_equivalence"
        ]

        self.assertEqual(finding["kind"], "not_compared")
        self.assertIn("scientific comparability", summary["decisions_not_earned"])
        self.assertIn("fit quality comparison", summary["decisions_not_earned"])
        self.assertEqual(candidate["warnings"], [])

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-reference-comparison-review.md").read_text(encoding="utf-8")

        self.assertIn("Selected Reference", review)
        self.assertIn("ordinary measurement mark", review)
        self.assertIn("Named Input Comparison", review)
        self.assertIn("changed parameter state", review)
        self.assertIn("same_observed_setup_binding", review)
        self.assertIn("quickly browse or overlay compatible measurements", review)
        self.assertIn("avoid using `gap`", review)
        self.assertIn("raw data, fit quality, hardware runtime state", review)


if __name__ == "__main__":
    unittest.main()
