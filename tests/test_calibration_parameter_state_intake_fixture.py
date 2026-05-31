from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_parameter_state_intake" / "basic_intake"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "intake-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-intake-summary.json").read_text(encoding="utf-8"))


class CalibrationParameterStateIntakeFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "intake-input.json",
            FIXTURE / "expected-intake-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_summary_boundary(self) -> None:
        summary = _expected_summary()

        self.assertEqual(summary["summary_policy"], "internal_validation_summary")
        self.assertIn("fixture_only", summary["reference_semantics"]["status"])
        self.assertIn("parameter-state storage mutation", summary["decisions_not_earned"])

    def test_intake_review_accepts_only_handoff_diff_paths(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["source_handoff"]["diff_paths"], ["qubits.qA.pi_amp"])
        self.assertEqual(
            candidate["intake_review"]["accepted_diff_paths"],
            candidate["source_handoff"]["diff_paths"],
        )
        self.assertEqual(candidate["source_handoff"]["apply_state"], "not_applied")

    def test_managed_state_tracks_changed_and_carried_entries(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        entries = {
            entry["path"]: entry for entry in candidate["managed_parameter_state"]["entries"]
        }

        self.assertEqual(entries["qubits.qA.pi_amp"]["value"], 0.437)
        self.assertEqual(
            entries["qubits.qA.pi_amp"]["change_source"],
            "accepted_calibration_handoff",
        )
        self.assertEqual(
            entries["qubits.qA.drive_frequency_hz"]["change_source"],
            "carried_forward_from_base_state",
        )

    def test_provenance_keeps_measurement_reference_only(self) -> None:
        provenance = _expected_summary()["candidate_summary"]["provenance"]

        self.assertEqual(provenance["source_observation"], "validated_calibration_handoff_summary")
        self.assertEqual(provenance["measurement_record_refs"], ["measurement-07001"])
        self.assertEqual(provenance["observation_links"][0]["payload_handling"], "reference_only")

    def test_no_side_effects_are_claimed(self) -> None:
        side_effects = _expected_summary()["candidate_summary"]["side_effects"]

        self.assertEqual(side_effects["storage_mutation"], "not_performed")
        self.assertEqual(side_effects["external_compatibility_output"], "not_produced")
        self.assertEqual(side_effects["hardware_write_back"], "not_performed")
        self.assertEqual(side_effects["durable_history"], "summary_only_not_written")

    def test_input_fixture_uses_parameter_state_route_authority(self) -> None:
        source = _input_fixture()

        self.assertEqual(
            source["calibration_parameter_state_intake_policy"]["intake_authority"],
            "parameter_state_management_route",
        )


if __name__ == "__main__":
    unittest.main()
