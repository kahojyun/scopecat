from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_storage_writer" / "basic_write"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "storage-writer-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-storage-writer-summary.json").read_text(encoding="utf-8")
    )


class ParameterStateStorageWriterFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "storage-writer-input.json",
            FIXTURE / "expected-storage-writer-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_storage_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertIn(
            "not final storage architecture", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(candidate["storage_policy"]["overwrite_behavior"], "no_overwrite")
        self.assertEqual(candidate["storage_request"]["approval_state"], "approved")
        self.assertIn("final storage architecture", expected["decisions_not_earned"])

    def test_write_results_include_digest_and_size_facts(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        results = {item["kind"]: item for item in candidate["write_results"]}

        self.assertEqual(results["parameter_state_manifest"]["bytes_written"], 3563)
        self.assertTrue(results["parameter_state_manifest"]["digest"].startswith("sha256:"))
        self.assertEqual(results["write_receipt"]["bytes_written"], 640)
        self.assertTrue(results["write_receipt"]["digest"].startswith("sha256:"))

    def test_provenance_and_exclusions_are_preserved(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["provenance"]["source_observation"], "adapter_declared_only")
        self.assertEqual(
            [entry["path"] for entry in candidate["excluded_preview_entries"]],
            ["readout.qA.frequency_hz", "readout.qA.calibration_table"],
        )
        self.assertEqual(candidate["parameter_state"]["entry_count"], 2)


if __name__ == "__main__":
    unittest.main()
