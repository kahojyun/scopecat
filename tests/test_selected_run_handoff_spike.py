from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spikes.selected_run_handoff.generate import generate_manifest, generate_review

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "minimal"


class SelectedRunHandoffSpikeTest(unittest.TestCase):
    def test_generates_expected_manifest(self) -> None:
        manifest = generate_manifest(FIXTURE)
        expected = json.loads((FIXTURE / "expected-handoff-manifest.json").read_text())

        self.assertEqual(manifest, expected)

    def test_generates_expected_review(self) -> None:
        manifest = generate_manifest(FIXTURE)
        review = generate_review(manifest)
        expected = (FIXTURE / "expected-handoff-review.md").read_text()

        self.assertEqual(review, expected)

    def test_omits_related_runs_from_minimal_default_export(self) -> None:
        manifest = generate_manifest(FIXTURE)

        self.assertNotIn("adjacent_observed_ids", manifest)
        self.assertNotIn("rejected_alternatives", manifest)
        self.assertIn("related-but-not-exported run context", manifest["decisions_not_earned"])

    def test_keeps_export_and_figure_boundaries_visible(self) -> None:
        manifest = generate_manifest(FIXTURE)
        selected = manifest["selected_runs"][0]
        warnings = {warning["code"] for warning in manifest["warnings"]}

        self.assertTrue(selected["no_silent_transform"])
        self.assertEqual(
            selected["source_reference"]["export_source"],
            "LAB_LOCAL:/redacted/datavault/selected-rabi-demo/selected-rabi-source.csv",
        )
        self.assertEqual(manifest["figure_readiness"]["status"], "partial")
        self.assertNotIn("no_silent_transform_source_data", warnings)
        self.assertNotIn("derived_relation_not_recomputed", warnings)
        self.assertIn("figure_readiness_partial", warnings)
        self.assertTrue(
            any("should not be silently compressed" in note for note in manifest["boundary_notes"])
        )
        self.assertTrue(
            any("does not recompute analysis" in note for note in manifest["boundary_notes"])
        )
        self.assertIn(
            "user/domain conclusions or reproducibility", manifest["decisions_not_earned"]
        )

    def test_reports_missing_selected_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_copy = Path(temp_dir) / "fixture"
            shutil.copytree(FIXTURE, fixture_copy)
            source_file = (
                fixture_copy / "source" / "selected-rabi-demo" / "selected-rabi-source.csv"
            )
            source_file.unlink()

            manifest = generate_manifest(fixture_copy)

        source_path = "source/selected-rabi-demo/selected-rabi-source.csv"
        self.assertIn(source_path, manifest["openability_summary"]["missing"])
        self.assertNotIn(source_path, manifest["openability_summary"]["present"])


if __name__ == "__main__":
    unittest.main()
