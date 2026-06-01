from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "source_agnostic_parameter_state_read_view" / "basic_read"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "read-view-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-read-view-summary.json").read_text(encoding="utf-8"))


class SourceAgnosticParameterStateReadViewFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "read-view-input.json",
            FIXTURE / "expected-read-view-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("universal provenance schema", expected["decisions_not_earned"])
        self.assertIn("typed payloads", expected["reference_semantics"]["provenance_boundary"])

    def test_read_requests_cover_adapter_and_calibration_sources(self) -> None:
        source_kinds = {request["source_kind"] for request in _input_fixture()["read_requests"]}

        self.assertEqual(source_kinds, {"adapter_import", "calibration_handoff"})

    def test_expected_output_preserves_typed_provenance(self) -> None:
        states = _expected_summary()["candidate_summary"]["stored_states"]
        by_kind = {state["source_kind"]: state for state in states}

        self.assertEqual(
            by_kind["adapter_import"]["typed_provenance"]["payload"]["source_observation"],
            "adapter_declared_only",
        )
        self.assertEqual(
            by_kind["calibration_handoff"]["typed_provenance"]["payload"]["source_observation"],
            "validated_calibration_handoff_summary",
        )

    def test_no_mutation_or_hardware_claims(self) -> None:
        policy = _expected_summary()["candidate_summary"]["read_view_policy"]

        self.assertEqual(policy["storage_mutation"], "not_performed")
        self.assertEqual(policy["compatibility_output"], "not_produced")
        self.assertEqual(policy["hardware_write_back"], "not_performed")


if __name__ == "__main__":
    unittest.main()
