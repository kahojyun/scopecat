from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "parameter_trusted_drift_projection" / "basic_trusted_history"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "parameter-trusted-drift-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-parameter-trusted-drift-summary.json").read_text(encoding="utf-8")
    )


class ParameterTrustedDriftProjectionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "parameter-trusted-drift-input.json",
            FIXTURE / "expected-parameter-trusted-drift-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_only_eligible_committed_states_contribute_points(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        projection = summary["drift_projections"][0]

        self.assertEqual(
            projection["state_filter"]["included_state_ids"],
            ["param-state-0002", "param-state-0004"],
        )
        self.assertEqual(
            projection["state_filter"]["excluded_state_ids"],
            ["param-state-0001", "param-state-0003"],
        )
        self.assertEqual(projection["rendered_plot"], "not_performed")

    def test_trusted_numeric_series_excludes_seed_and_exploratory_values(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        series = {
            path_series["path"]: path_series
            for path_series in summary["drift_projections"][0]["path_series"]
        }

        drive_points = series["qubits.qA.drive_frequency_hz"]["points"]
        pi_points = series["qubits.qA.pi_amp"]["points"]

        self.assertEqual(
            [point["state_id"] for point in drive_points], ["param-state-0002", "param-state-0004"]
        )
        self.assertEqual([point["value"] for point in drive_points], [5012500000, 5014000000])
        self.assertEqual([point["value"] for point in pi_points], [0.42, 0.415])

        encoded_points = json.dumps(drive_points + pi_points)
        self.assertNotIn("5010000000", encoded_points)
        self.assertNotIn("5016000000", encoded_points)
        self.assertEqual(
            source["parameter_states"][0]["history_plot_eligibility"],
            "exclude_from_trusted_drift_plots",
        )

    def test_untrusted_and_non_scalar_entries_are_findings_not_points(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        series = {
            path_series["path"]: path_series
            for path_series in summary["drift_projections"][0]["path_series"]
        }
        findings = summary["review_findings"]

        self.assertEqual(series["readout.qA.frequency_hz"]["point_count"], 0)
        self.assertEqual(series["readout.qA.calibration_table"]["point_count"], 0)
        self.assertIn(
            "skipped_untrusted_entry",
            [finding["kind"] for finding in findings],
        )
        self.assertIn(
            "skipped_non_scalar_entry",
            [finding["kind"] for finding in findings],
        )

    def test_structured_summary_states_fixture_boundary(self) -> None:
        summary = _expected_summary()
        semantics = summary["reference_semantics"]
        candidate = summary["candidate_summary"]

        self.assertIn("not a final parameter schema", semantics["contract_guard"])
        self.assertIn("eligible committed parameter states", semantics["trusted_history"])
        self.assertEqual(candidate["policy"]["drift_plot_rendering"], "not_performed")
        self.assertEqual(candidate["policy"]["hardware_write_back"], "not_performed")
        self.assertIn("rendered drift plotting", summary["decisions_not_earned"])
        self.assertIn("internal validation artifact", summary["boundary_notes"][4])


if __name__ == "__main__":
    unittest.main()
