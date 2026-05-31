from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_storage_read_view" / "basic_read"


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-read-view-summary.json").read_text(encoding="utf-8"))


class ParameterStateStorageReadViewFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        paths = [
            FIXTURE / "read-view-input.json",
            FIXTURE / "expected-read-view-summary.json",
            (
                FIXTURE
                / "storage"
                / "parameter-states"
                / "param-state-imported-0001"
                / "parameter-state.json"
            ),
            (
                FIXTURE
                / "storage"
                / "parameter-states"
                / "param-state-imported-0001"
                / "write-receipt.json"
            ),
        ]
        for path in paths:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_read_view_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn(
            "read-only explicit manifest", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(candidate["read_view_policy"]["storage_mutation"], "not_performed")
        self.assertEqual(candidate["read_view_policy"]["catalog_discovery"], "not_performed")
        self.assertEqual(
            candidate["read_view_policy"]["legacy_source_observation"], "not_performed"
        )
        self.assertIn("catalog or index discovery", expected["decisions_not_earned"])

    def test_expected_summary_includes_digest_size_and_continuity_facts(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        observed = {item["kind"]: item for item in candidate["observed_files"]}

        self.assertEqual(observed["parameter_state_manifest"]["observed_size_bytes"], 3563)
        self.assertTrue(
            observed["parameter_state_manifest"]["observed_digest"].startswith("sha256:")
        )
        self.assertEqual(observed["write_receipt"]["observed_size_bytes"], 640)
        self.assertEqual(
            candidate["receipt"]["manifest_digest"],
            observed["parameter_state_manifest"]["observed_digest"],
        )
        self.assertEqual(
            candidate["receipt"]["manifest_size_bytes"],
            observed["parameter_state_manifest"]["observed_size_bytes"],
        )

    def test_trusted_entries_provenance_and_exclusions_are_visible(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["parameter_state"]["entry_count"], 2)
        self.assertEqual(
            [entry["path"] for entry in candidate["trusted_entries"]],
            ["qubits.qA.drive_frequency_hz", "qubits.qA.pi_amp"],
        )
        self.assertEqual(candidate["provenance"]["source_observation"], "adapter_declared_only")
        self.assertEqual(
            [entry["path"] for entry in candidate["excluded_preview_entries"]],
            ["readout.qA.frequency_hz", "readout.qA.calibration_table"],
        )


if __name__ == "__main__":
    unittest.main()
