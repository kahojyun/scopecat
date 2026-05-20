from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spikes.selected_measurement_export.generate import (
    generate_candidate_summary,
    generate_review,
    generate_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "preview_ready_measurement_export"


class SelectedMeasurementExportSpikeTest(unittest.TestCase):
    def test_generates_expected_export_summary(self) -> None:
        summary = generate_summary(FIXTURE)
        expected = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )

        self.assertEqual(summary, expected)

    def test_generates_expected_candidate_summary(self) -> None:
        summary = generate_candidate_summary(FIXTURE)
        expected = json.loads(
            (FIXTURE / "expected-export-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)

    def test_generates_expected_export_review(self) -> None:
        summary = generate_summary(FIXTURE)
        review = generate_review(summary)
        expected = (FIXTURE / "expected-export-review.md").read_text(encoding="utf-8")

        self.assertEqual(review, expected)

    def test_degraded_preview_does_not_infer_from_source_header(self) -> None:
        summary = generate_candidate_summary(FIXTURE)
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

    def test_preserves_export_source_as_provenance(self) -> None:
        summary = generate_candidate_summary(FIXTURE)
        export_sources = {
            measurement["legacy_data_id"]: measurement["export_source"]
            for measurement in summary["measurements"]
        }

        self.assertEqual(
            export_sources,
            {
                1001: (
                    "LAB_LOCAL:/redacted/datavault/session-alpha/01001_qA_rabi_20260518_101500.csv"
                ),
                1002: (
                    "LAB_LOCAL:/redacted/datavault/session-alpha/01002_qA_t1_20260518_104500.csv"
                ),
            },
        )

    def test_rejects_unsupported_fixture_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            input_path = fixture_copy / "export-input.json"
            source = json.loads(input_path.read_text(encoding="utf-8"))
            source["fixture_id"] = "not-the-supported-fixture"
            input_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unsupported fixture_id"):
                generate_summary(fixture_copy)

    def test_only_selected_measurements_are_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            input_path = fixture_copy / "export-input.json"
            source = json.loads(input_path.read_text(encoding="utf-8"))
            unselected = dict(source["measurements"][0])
            unselected["legacy_data_id"] = 9999
            unselected["export_source"] = "LAB_LOCAL:/redacted/unselected.csv"
            source["measurements"].append(unselected)
            input_path.write_text(json.dumps(source), encoding="utf-8")

            summary = generate_candidate_summary(fixture_copy)

        self.assertEqual(
            [measurement["legacy_data_id"] for measurement in summary["measurements"]],
            [1001, 1002],
        )

    def test_primary_data_path_must_match_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            input_path = fixture_copy / "export-input.json"
            source = json.loads(input_path.read_text(encoding="utf-8"))
            source["measurements"][0]["default_bundle"][0]["path"] = (
                "source/session-alpha/wrong.csv"
            )
            input_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "primary_data path"):
                generate_summary(fixture_copy)

    def test_plot_candidate_source_must_match_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            input_path = fixture_copy / "export-input.json"
            source = json.loads(input_path.read_text(encoding="utf-8"))
            source["measurements"][0]["preview_metadata"]["plot_candidates"][0]["source"] = (
                "source/session-alpha/wrong.csv"
            )
            input_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "plot candidate source"):
                generate_summary(fixture_copy)


if __name__ == "__main__":
    unittest.main()
