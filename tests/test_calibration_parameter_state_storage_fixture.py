from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_parameter_state_storage" / "basic_write"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "storage-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-storage-summary.json").read_text(encoding="utf-8"))


class CalibrationParameterStateStorageFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "storage-input.json",
            FIXTURE / "expected-storage-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertEqual(candidate["storage_policy"]["overwrite_behavior"], "no_overwrite")
        self.assertIn("storage read-view compatibility", expected["decisions_not_earned"])

    def test_write_results_include_digest_and_size_facts(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        results = {item["kind"]: item for item in candidate["write_results"]}

        self.assertEqual(results["parameter_state_manifest"]["bytes_written"], 3651)
        self.assertTrue(results["parameter_state_manifest"]["digest"].startswith("sha256:"))
        self.assertEqual(results["write_receipt"]["bytes_written"], 828)
        self.assertTrue(results["write_receipt"]["digest"].startswith("sha256:"))

    def test_calibration_provenance_is_preserved(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["provenance"]["source_observation"],
            "validated_calibration_handoff_summary",
        )
        self.assertEqual(candidate["provenance"]["measurement_record_refs"], ["measurement-07001"])
        self.assertEqual(candidate["source_handoff"]["apply_state"], "not_applied")

    def test_no_compatibility_or_hardware_side_effects_are_claimed(self) -> None:
        source = _input_fixture()

        self.assertEqual(
            source["side_effect_claims"]["external_compatibility_output"],
            "not_produced",
        )
        self.assertEqual(source["side_effect_claims"]["hardware_write_back"], "not_performed")
        self.assertEqual(source["side_effect_claims"]["rollback"], "not_defined")


if __name__ == "__main__":
    unittest.main()
