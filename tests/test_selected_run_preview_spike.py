from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spikes.selected_run_preview.generate import generate_preview, generate_review

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "minimal"


class SelectedRunPreviewSpikeTest(unittest.TestCase):
    def test_generates_expected_preview_json(self) -> None:
        preview = generate_preview(FIXTURE)
        expected = json.loads((FIXTURE / "expected-preview.json").read_text())

        self.assertEqual(preview, expected)

    def test_generates_expected_preview_review(self) -> None:
        preview = generate_preview(FIXTURE)
        review = generate_review(preview)
        expected = (FIXTURE / "expected-preview.md").read_text()

        self.assertEqual(review, expected)

    def test_validates_declared_column_names_against_csv_header(self) -> None:
        preview = generate_preview(FIXTURE)
        validation = preview["column_validation"]

        self.assertEqual(validation["status"], "pass")
        self.assertEqual(validation["missing_declared_columns"], [])
        self.assertEqual(validation["extra_source_columns"], [])
        self.assertIn("role semantic correctness", validation["not_validated"])

    def test_preview_stays_in_one_dimensional_csv_boundary(self) -> None:
        preview = generate_preview(FIXTURE)

        self.assertEqual(preview["plot_spec"]["x"]["column"], "drive_amp")
        self.assertEqual(preview["plot_spec"]["y"]["column"], "iq_i")
        self.assertEqual(
            [candidate["y"]["column"] for candidate in preview["plot_candidates"]],
            ["iq_i", "iq_q"],
        )
        self.assertIn("2d_grid_csv", preview["future_scan_shape_backlog"])
        self.assertIn("general data schema", preview["decisions_not_earned"])
        self.assertIn("plot rendering", preview["decisions_not_earned"])

    def test_preview_table_includes_all_declared_measured_responses(self) -> None:
        preview = generate_preview(FIXTURE)
        table = preview["preview_table"]

        self.assertEqual(table["columns"], ["drive_amp", "iq_i", "iq_q", "bias_v"])
        self.assertEqual(table["rows"][0]["iq_i"], 0.812)
        self.assertEqual(table["rows"][0]["iq_q"], 0.113)

    def test_missing_declared_column_returns_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            input_path = fixture_copy / "handoff-input.json"
            source = json.loads(input_path.read_text(encoding="utf-8"))
            source["figure_readiness"]["source_columns"].append(
                {
                    "name": "missing_response",
                    "role": "measured_response",
                    "unit": "arb",
                }
            )
            input_path.write_text(json.dumps(source), encoding="utf-8")

            preview = generate_preview(fixture_copy)
            review = generate_review(preview)

        self.assertEqual(preview["column_validation"]["status"], "fail")
        self.assertIn(
            "missing_response",
            preview["column_validation"]["missing_declared_columns"],
        )
        self.assertEqual(preview["preview_table"]["rows"], [])
        self.assertIsNone(preview["plot_spec"])
        self.assertIn("Plot spec unavailable.", review)


if __name__ == "__main__":
    unittest.main()
