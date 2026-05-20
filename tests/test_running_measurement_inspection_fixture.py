from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "running_measurement_inspection"
FIXTURES = {
    "partial_sweep": FIXTURE_ROOT / "partial_sweep",
    "partial_heatmap": FIXTURE_ROOT / "partial_heatmap",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RunningMeasurementInspectionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for fixture in FIXTURES.values():
            for path in [
                fixture / "inspection-input.json",
                fixture / "expected-inspection-summary.json",
            ]:
                with self.subTest(path=path):
                    _load_json(path)

    def test_expected_summary_has_wrapper_and_candidate_summary(self) -> None:
        fixture = FIXTURES["partial_sweep"]
        summary = _load_json(fixture / "expected-inspection-summary.json")
        candidate = summary["candidate_summary"]

        self.assertEqual(summary["status"], "expected_validation_output")
        self.assertEqual(
            summary["reference_semantics"]["status"],
            "fixture_paths_are_package_relative",
        )
        self.assertEqual(candidate["measurement"]["measurement_id"], "run-live-02001")
        self.assertEqual(candidate["lifecycle"]["state"], "recording")
        self.assertEqual(candidate["progress"]["recorded_points"], 14)
        self.assertEqual(candidate["progress"]["latest_completed_unit"]["sweep_index"], 0)
        self.assertTrue(candidate["progress"]["latest_completed_unit"]["complete"])
        self.assertTrue(candidate["progress"]["latest_completed_unit"]["default_preview_candidate"])
        self.assertFalse(candidate["progress"]["current_partial_unit"]["complete"])
        self.assertFalse(candidate["progress"]["current_partial_unit"]["default_preview_candidate"])

    def test_heatmap_expected_summary_has_wrapper_and_candidate_summary(self) -> None:
        fixture = FIXTURES["partial_heatmap"]
        summary = _load_json(fixture / "expected-inspection-summary.json")
        candidate = summary["candidate_summary"]

        self.assertEqual(summary["status"], "expected_validation_output")
        self.assertEqual(
            summary["reference_semantics"]["status"],
            "fixture_paths_are_package_relative",
        )
        self.assertEqual(candidate["measurement"]["measurement_id"], "run-live-03001")
        self.assertEqual(candidate["lifecycle"]["state"], "recording")
        self.assertEqual(candidate["progress"]["recorded_points"], 13)
        self.assertEqual(
            candidate["progress"]["latest_completed_unit"]["kind"], "rectangular_prefix"
        )
        self.assertTrue(candidate["progress"]["latest_completed_unit"]["complete"])
        self.assertTrue(candidate["progress"]["latest_completed_unit"]["default_preview_candidate"])
        self.assertFalse(candidate["progress"]["current_partial_unit"]["complete"])
        self.assertFalse(candidate["progress"]["current_partial_unit"]["default_preview_candidate"])

    def test_partial_sweep_recorded_rows_match_progress_state(self) -> None:
        fixture = FIXTURES["partial_sweep"]
        summary = _load_json(fixture / "expected-inspection-summary.json")
        candidate = summary["candidate_summary"]
        data_path = fixture / candidate["latest_data_reference"]["path"]
        with data_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        latest_filter = candidate["latest_data_reference"]["latest_completed_filter"]
        latest_completed_rows = [
            row for row in rows if int(row[latest_filter["column"]]) == latest_filter["equals"]
        ]
        current_partial = candidate["progress"]["current_partial_unit"]
        current_partial_rows = [
            row for row in rows if int(row["sweep_index"]) == current_partial["sweep_index"]
        ]

        self.assertEqual(len(rows), candidate["progress"]["recorded_points"])
        self.assertEqual(
            len(latest_completed_rows),
            candidate["progress"]["latest_completed_unit"]["row_count"],
        )
        self.assertEqual(len(current_partial_rows), current_partial["recorded_points"])

    def test_partial_heatmap_recorded_rows_match_progress_state(self) -> None:
        fixture = FIXTURES["partial_heatmap"]
        summary = _load_json(fixture / "expected-inspection-summary.json")
        candidate = summary["candidate_summary"]
        data_path = fixture / candidate["latest_data_reference"]["path"]
        with data_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        latest_filter = candidate["latest_data_reference"]["latest_completed_filter"]
        latest_completed_rows = [
            row
            for row in rows
            if float(row[latest_filter["column"]]) <= latest_filter["max_inclusive"]
        ]
        current_partial = candidate["progress"]["current_partial_unit"]
        current_partial_rows = [
            row
            for row in rows
            if float(row[current_partial["outer_axis"]]) == current_partial["outer_value"]
        ]

        self.assertEqual(len(rows), candidate["progress"]["recorded_points"])
        self.assertEqual(
            len(latest_completed_rows),
            candidate["progress"]["latest_completed_unit"]["point_count"],
        )
        self.assertEqual(len(current_partial_rows), current_partial["recorded_points"])

    def test_attention_basis_is_explicit(self) -> None:
        for fixture in FIXTURES.values():
            with self.subTest(fixture=fixture.name):
                source = _load_json(fixture / "inspection-input.json")
                summary = _load_json(fixture / "expected-inspection-summary.json")
                candidate = summary["candidate_summary"]

                self.assertEqual(
                    source["attention_policy"]["stale_after_seconds"],
                    candidate["attention_basis"]["stale_after_seconds"],
                )
                self.assertIn("latest_data_age_seconds", candidate["attention_basis"])

    def test_heatmap_preview_declares_two_axes_and_heatmap_candidates(self) -> None:
        fixture = FIXTURES["partial_heatmap"]
        summary = _load_json(fixture / "expected-inspection-summary.json")
        candidate = summary["candidate_summary"]
        preview = candidate["preview"]

        self.assertEqual(
            preview["axis_order"],
            ["bias_v", "drive_freq_ghz"],
        )
        self.assertEqual(preview["shape_kind"], "partial_2d_grid_table")
        self.assertEqual(
            preview["row_order"],
            "bias_v_outer_drive_freq_ghz_inner_fastest",
        )
        self.assertEqual(
            {plot["kind"] for plot in preview["plot_candidates"]},
            {"heatmap"},
        )

    def test_attention_codes_match_expected_attention(self) -> None:
        for fixture in FIXTURES.values():
            with self.subTest(fixture=fixture.name):
                source = _load_json(fixture / "inspection-input.json")
                summary = _load_json(fixture / "expected-inspection-summary.json")
                candidate = summary["candidate_summary"]

                self.assertEqual(
                    source["attention_expected"],
                    [attention["code"] for attention in candidate["attention"]],
                )

    def test_partial_progress_and_monitor_state_are_not_warnings(self) -> None:
        for fixture in FIXTURES.values():
            with self.subTest(fixture=fixture.name):
                summary = _load_json(fixture / "expected-inspection-summary.json")
                candidate = summary["candidate_summary"]
                attention_codes = [attention["code"] for attention in candidate["attention"]]

                self.assertNotIn("recording", attention_codes)
                self.assertNotIn("current_partial_unit", attention_codes)
                self.assertFalse(candidate["ephemeral_monitor_state"]["durable"])
                self.assertTrue(
                    any(
                        isinstance(value, dict) and value.get("status") == "preview_only"
                        for value in candidate["ephemeral_monitor_state"].values()
                    )
                )

    def test_review_states_running_inspection_boundary(self) -> None:
        review = (FIXTURES["partial_sweep"] / "expected-inspection-review.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Fixture Wrapper", review)
        self.assertIn("Candidate Summary Review", review)
        self.assertIn("latest completed unit: sweep `0`", review)
        self.assertIn("Temporary range selection and preview fits", review)
        self.assertIn("not controlling instruments", review)

    def test_heatmap_review_states_shape_boundary(self) -> None:
        review = (FIXTURES["partial_heatmap"] / "expected-inspection-review.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Fixture Wrapper", review)
        self.assertIn("Candidate Summary Review", review)
        self.assertIn("latest completed unit: rectangular prefix", review)
        self.assertIn("incomplete row", review)
        self.assertIn("warning by itself", review)
        self.assertIn("without defining ragged scan", review)


if __name__ == "__main__":
    unittest.main()
