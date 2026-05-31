from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "adapter_parameter_import_review_commit" / "basic_review_commit"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "review-commit-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-review-commit-summary.json").read_text(encoding="utf-8"))


class AdapterParameterImportReviewCommitFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "review-commit-input.json",
            FIXTURE / "expected-review-commit-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_review_gate_accepts_only_candidate_entry_paths(self) -> None:
        summary = _expected_summary()
        candidate = summary["candidate_summary"]
        managed = candidate["managed_parameter_state"]

        self.assertIn("Only explicitly accepted", summary["reference_semantics"]["review_gate"])
        self.assertEqual(
            candidate["review"]["accepted_entry_paths"],
            ["qubits.qA.drive_frequency_hz", "qubits.qA.pi_amp"],
        )
        self.assertEqual(
            [entry["path"] for entry in managed["entries"]],
            candidate["review"]["accepted_entry_paths"],
        )

    def test_skipped_preview_entries_remain_excluded(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        excluded = candidate["excluded_preview_entries"]

        self.assertEqual(
            [entry["path"] for entry in excluded],
            ["readout.qA.frequency_hz", "readout.qA.calibration_table"],
        )
        self.assertEqual(
            {entry["disposition"] for entry in excluded},
            {"not_committed_to_managed_parameter_state"},
        )

    def test_provenance_is_preserved_without_source_observation_claim(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        provenance = candidate["provenance"]

        self.assertEqual(provenance["adapter_id"], "public-safe-parameter-adapter")
        self.assertEqual(provenance["source_observation"], "adapter_declared_only")
        self.assertEqual(
            [source["source_format"] for source in provenance["legacy_sources"]],
            ["legacy_parameters_json", "xlsx_parameter_table"],
        )

    def test_no_side_effects_are_claimed(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["policy"]["managed_parameter_state_creation"], "summary_only_not_written"
        )
        self.assertEqual(candidate["side_effects"]["legacy_source_parsing"], "not_performed")
        self.assertEqual(candidate["side_effects"]["storage_mutation"], "not_performed")
        self.assertEqual(candidate["side_effects"]["hardware_write_back"], "not_performed")
        self.assertIn("storage writer", _expected_summary()["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
