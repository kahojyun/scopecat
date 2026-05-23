from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.running_measurement_inspection import (
    build_running_measurement_inspection_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "running_measurement_inspection"
FIXTURES = {
    "partial_sweep": FIXTURE_ROOT / "partial_sweep",
    "partial_heatmap": FIXTURE_ROOT / "partial_heatmap",
}


def _load_input(name: str) -> dict:
    return json.loads((FIXTURES[name] / "inspection-input.json").read_text(encoding="utf-8"))


def _load_expected(name: str) -> dict:
    return json.loads(
        (FIXTURES[name] / "expected-inspection-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class RunningMeasurementInspectionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary_for_all_fixtures(self) -> None:
        for name in FIXTURES:
            with self.subTest(fixture=name):
                summary = build_running_measurement_inspection_summary(_load_input(name))

                self.assertEqual(summary, _load_expected(name))
                self.assertNotIn("reference_semantics", summary)
                self.assertNotIn("source_fixture", summary)
                self.assertNotIn("status", summary)

    def test_latest_completed_unit_is_preview_candidate_not_current_partial_unit(self) -> None:
        summary = build_running_measurement_inspection_summary(_load_input("partial_sweep"))

        self.assertTrue(summary["progress"]["latest_completed_unit"]["complete"])
        self.assertTrue(summary["progress"]["latest_completed_unit"]["default_preview_candidate"])
        self.assertFalse(summary["progress"]["current_partial_unit"]["complete"])
        self.assertFalse(summary["progress"]["current_partial_unit"]["default_preview_candidate"])

    def test_freshness_attention_uses_declared_observation_time(self) -> None:
        stale_summary = build_running_measurement_inspection_summary(_load_input("partial_sweep"))
        fresh_summary = build_running_measurement_inspection_summary(_load_input("partial_heatmap"))

        self.assertEqual(
            stale_summary["attention"],
            [
                {
                    "code": "latest_data_stale",
                    "subject": "lifecycle.last_update_at",
                    "basis": "latest_data_age_seconds > stale_after_seconds",
                    "message": "Latest update is 92 seconds before the fixture observation time.",
                }
            ],
        )
        self.assertEqual(fresh_summary["attention"], [])

    def test_monitor_claim_guards_are_not_promoted_to_durable_summary(self) -> None:
        summary = build_running_measurement_inspection_summary(_load_input("partial_heatmap"))

        self.assertFalse(summary["ephemeral_monitor_state"]["durable"])
        self.assertNotIn(
            "claim_guard",
            summary["ephemeral_monitor_state"]["temporary_feature_preview"],
        )
        self.assertEqual(
            summary["ephemeral_monitor_state"]["temporary_feature_preview"]["status"],
            "preview_only",
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input("partial_sweep")
        summary = build_running_measurement_inspection_summary(source)

        source["progress"]["latest_completed_unit"]["row_count"] = 999
        source["preview_metadata"]["declared_columns"][0]["label"] = "mutated"
        source["ephemeral_monitor_state"]["selected_range"]["min"] = -999

        self.assertEqual(summary["progress"]["latest_completed_unit"]["row_count"], 10)
        self.assertEqual(summary["preview"]["declared_roles"][0]["label"], "Drive frequency")
        self.assertEqual(summary["ephemeral_monitor_state"]["selected_range"]["min"], 4.996)

    def test_private_source_identity_is_rejected(self) -> None:
        source = _load_input("partial_sweep")
        source["measurement"]["source_identity"] = "/Users/example/lab/run.csv"

        with self.assertRaisesRegex(ValueError, "source_identity"):
            build_running_measurement_inspection_summary(source)

    def test_absolute_redacted_source_identity_is_rejected(self) -> None:
        source = _load_input("partial_sweep")
        source["measurement"]["source_identity"] = "/tmp/redacted/live.csv"

        with self.assertRaisesRegex(ValueError, "source_identity"):
            build_running_measurement_inspection_summary(source)

    def test_unredacted_source_identity_is_rejected(self) -> None:
        source = _load_input("partial_sweep")
        source["measurement"]["source_identity"] = "LAB_LOCAL:/datavault/live-sweep-demo/run.csv"

        with self.assertRaisesRegex(ValueError, "source_identity"):
            build_running_measurement_inspection_summary(source)

    def test_source_identity_path_portion_is_validated(self) -> None:
        for source_identity in [
            "LAB_LOCAL:C:/redacted/private-run.csv",
            "LAB_LOCAL:~/redacted/run.csv",
        ]:
            with self.subTest(source_identity=source_identity):
                source = _load_input("partial_sweep")
                source["measurement"]["source_identity"] = source_identity

                with self.assertRaisesRegex(ValueError, "source_identity"):
                    build_running_measurement_inspection_summary(source)

    def test_source_identity_authority_must_be_supported(self) -> None:
        source = _load_input("partial_sweep")
        source["measurement"]["source_identity"] = (
            "UNKNOWN:/redacted/datavault/live-sweep-demo/run.csv"
        )

        with self.assertRaisesRegex(ValueError, "source_identity authority"):
            build_running_measurement_inspection_summary(source)

    def test_absolute_latest_data_reference_is_rejected(self) -> None:
        source = _load_input("partial_sweep")
        source["latest_data_reference"]["path"] = "/private/live.csv"

        with self.assertRaisesRegex(ValueError, "latest data reference path"):
            build_running_measurement_inspection_summary(source)

    def test_parent_traversing_latest_data_reference_is_rejected(self) -> None:
        source = _load_input("partial_sweep")
        source["latest_data_reference"]["path"] = "source/../run.csv"

        with self.assertRaisesRegex(ValueError, "latest data reference path"):
            build_running_measurement_inspection_summary(source)

    def test_plot_candidate_source_must_match_latest_data_reference(self) -> None:
        source = _load_input("partial_sweep")
        source["preview_metadata"]["plot_candidates"][0]["source"] = "source/wrong.csv"

        with self.assertRaisesRegex(ValueError, "plot candidate source"):
            build_running_measurement_inspection_summary(source)

    def test_plot_candidate_axes_must_reference_declared_columns(self) -> None:
        source = _load_input("partial_heatmap")
        source["preview_metadata"]["plot_candidates"][0]["z"] = "undeclared_signal"

        with self.assertRaisesRegex(ValueError, "declared columns"):
            build_running_measurement_inspection_summary(source)

    def test_current_partial_unit_cannot_be_silently_promoted_to_preview_candidate(self) -> None:
        source = _load_input("partial_sweep")
        source["progress"]["current_partial_unit"]["default_preview_candidate"] = True

        with self.assertRaisesRegex(ValueError, "current partial unit"):
            build_running_measurement_inspection_summary(source)

    def test_ephemeral_monitor_state_must_not_be_durable(self) -> None:
        source = _load_input("partial_sweep")
        source["ephemeral_monitor_state"]["durable"] = True

        with self.assertRaisesRegex(ValueError, "ephemeral monitor state"):
            build_running_measurement_inspection_summary(source)

    def test_ephemeral_monitor_state_rejects_unknown_pass_through_data(self) -> None:
        source = _load_input("partial_sweep")
        source["ephemeral_monitor_state"]["saved_analysis_result"] = {
            "status": "saved",
            "path": "/tmp/redacted/result.json",
        }

        with self.assertRaisesRegex(ValueError, "ephemeral monitor state shape"):
            build_running_measurement_inspection_summary(source)

    def test_selected_range_axis_must_reference_declared_columns(self) -> None:
        source = _load_input("partial_sweep")
        source["ephemeral_monitor_state"]["selected_range"]["axis"] = "private_axis"

        with self.assertRaisesRegex(ValueError, "selected range axis"):
            build_running_measurement_inspection_summary(source)

    def test_selected_region_axes_must_reference_declared_columns(self) -> None:
        source = _load_input("partial_heatmap")
        source["ephemeral_monitor_state"]["selected_region"]["x_axis"] = "private_axis"

        with self.assertRaisesRegex(ValueError, "selected region axes"):
            build_running_measurement_inspection_summary(source)

    def test_temporary_feature_minimum_keys_must_match_declared_axes(self) -> None:
        source = _load_input("partial_heatmap")
        source["ephemeral_monitor_state"]["temporary_feature_preview"]["minimum_at"] = {
            "private_axis": 0,
            "drive_freq_ghz": 5,
        }

        with self.assertRaisesRegex(ValueError, "minimum_at"):
            build_running_measurement_inspection_summary(source)

    def test_saved_decisions_are_rejected_until_slice_earns_durable_records(self) -> None:
        source = _load_input("partial_sweep")
        source["saved_decisions"].append(
            {
                "kind": "parameter_write_back",
                "local_path": "/tmp/redacted/params.json",
            }
        )

        with self.assertRaisesRegex(ValueError, "saved decisions"):
            build_running_measurement_inspection_summary(source)

    def test_current_partial_counts_must_be_internally_consistent(self) -> None:
        source = _load_input("partial_sweep")
        source["progress"]["current_partial_unit"]["recorded_points"] = 11

        with self.assertRaisesRegex(ValueError, "current partial sweep recorded_points"):
            build_running_measurement_inspection_summary(source)

    def test_sweep_expected_totals_must_be_internally_consistent(self) -> None:
        source = _load_input("partial_sweep")
        source["progress"]["expected_points"] = 31

        with self.assertRaisesRegex(ValueError, "sweep expected_points"):
            build_running_measurement_inspection_summary(source)

    def test_sweep_unit_indices_must_match_recorded_progress(self) -> None:
        source = _load_input("partial_sweep")
        source["progress"]["current_partial_unit"]["sweep_index"] = 2

        with self.assertRaisesRegex(ValueError, "current partial sweep index"):
            build_running_measurement_inspection_summary(source)

    def test_rectangular_prefix_counts_must_be_internally_consistent(self) -> None:
        source = _load_input("partial_heatmap")
        source["progress"]["latest_completed_unit"]["point_count"] = 9

        with self.assertRaisesRegex(ValueError, "rectangular prefix point_count"):
            build_running_measurement_inspection_summary(source)

    def test_rectangular_expected_totals_must_be_internally_consistent(self) -> None:
        source = _load_input("partial_heatmap")
        source["progress"]["expected_points"] = 21

        with self.assertRaisesRegex(ValueError, "rectangular prefix expected_points"):
            build_running_measurement_inspection_summary(source)

    def test_latest_completed_filter_column_must_be_declared(self) -> None:
        source = _load_input("partial_sweep")
        source["latest_data_reference"]["latest_completed_filter"]["column"] = "private_column"

        with self.assertRaisesRegex(ValueError, "latest completed filter column"):
            build_running_measurement_inspection_summary(source)

    def test_sweep_latest_completed_filter_must_match_latest_unit(self) -> None:
        source = _load_input("partial_sweep")
        source["latest_data_reference"]["latest_completed_filter"]["equals"] = 99

        with self.assertRaisesRegex(ValueError, "latest sweep index"):
            build_running_measurement_inspection_summary(source)

    def test_rectangular_latest_completed_filter_must_match_latest_unit(self) -> None:
        source = _load_input("partial_heatmap")
        source["latest_data_reference"]["latest_completed_filter"]["max_inclusive"] = 0.02

        with self.assertRaisesRegex(ValueError, "latest outer value"):
            build_running_measurement_inspection_summary(source)

    def test_filter_zero_values_must_not_be_booleans(self) -> None:
        source = _load_input("partial_sweep")
        source["progress"]["latest_completed_unit"]["sweep_index"] = False

        with self.assertRaisesRegex(ValueError, "latest completed sweep index"):
            build_running_measurement_inspection_summary(source)

    def test_current_partial_row_must_not_overlap_completed_prefix(self) -> None:
        source = _load_input("partial_heatmap")
        source["progress"]["current_partial_unit"]["outer_value"] = 0

        with self.assertRaisesRegex(ValueError, "outer_value"):
            build_running_measurement_inspection_summary(source)

    def test_observed_at_must_not_precede_latest_update(self) -> None:
        source = copy.deepcopy(_load_input("partial_heatmap"))
        source["observed_at"] = "2026-05-19T11:21:00Z"

        with self.assertRaisesRegex(ValueError, "observed_at"):
            build_running_measurement_inspection_summary(source)

    def test_fractional_observed_at_must_not_precede_latest_update(self) -> None:
        source = copy.deepcopy(_load_input("partial_heatmap"))
        source["observed_at"] = "2026-05-19T11:22:01.900Z"

        with self.assertRaisesRegex(ValueError, "observed_at"):
            build_running_measurement_inspection_summary(source)


if __name__ == "__main__":
    unittest.main()
