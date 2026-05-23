from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_write_compatibility_output" / "basic_output_plan"


def _input_fixture() -> dict:
    return json.loads(
        (FIXTURE / "parameter-write-compatibility-input.json").read_text(encoding="utf-8")
    )


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-parameter-write-compatibility-summary.json").read_text(
            encoding="utf-8"
        )
    )


class ParameterWriteCompatibilityOutputFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "parameter-write-compatibility-input.json",
            FIXTURE / "expected-parameter-write-compatibility-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_external_path_is_target_not_authority(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        candidate = summary["candidate_summary"]
        output = candidate["compatibility_outputs"][0]

        self.assertEqual(
            candidate["policy"]["parameter_authority"],
            "scopecat_parameter_state",
        )
        self.assertEqual(output["target"]["target_role"], "external_compatibility_target")
        self.assertEqual(
            output["target"]["path"],
            source["compatibility_outputs"][0]["target"]["path"],
        )
        self.assertIn("compatibility target", summary["boundary_notes"][0])
        self.assertIn("external JSON authority", summary["decisions_not_earned"])

    def test_only_trusted_scalar_entries_are_planned(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        output = summary["compatibility_outputs"][0]
        entries = {entry["path"]: entry for entry in output["entries"]}

        self.assertEqual(
            output["emit_state_counts"],
            {"planned": 3, "skipped_schema_limited": 1, "skipped_untrusted": 1},
        )
        self.assertEqual(entries["qubits.qA.pi_amp"]["emit_state"], "planned")
        self.assertEqual(entries["qubits.qA.pi_amp"]["value"], 0.42)
        self.assertEqual(entries["readout.qA.frequency_hz"]["emit_state"], "skipped_untrusted")
        self.assertNotIn("value", entries["readout.qA.frequency_hz"])
        self.assertEqual(
            entries["readout.qA.calibration_table"]["emit_state"],
            "skipped_schema_limited",
        )
        self.assertNotIn("value", entries["readout.qA.calibration_table"])

    def test_review_findings_capture_skips_without_hardware_claims(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        findings = summary["review_findings"]

        self.assertEqual(
            [finding["kind"] for finding in findings],
            ["skipped_untrusted", "skipped_schema_limited"],
        )
        self.assertEqual(summary["policy"]["file_write"], "not_performed")
        self.assertEqual(summary["policy"]["hardware_write_back"], "not_performed")
        self.assertEqual(summary["policy"]["current_hardware_state_claim"], "not_claimed")

    def test_structured_summary_states_fixture_boundary(self) -> None:
        summary = _expected_summary()
        semantics = summary["reference_semantics"]

        self.assertIn("not a final parameter schema", semantics["contract_guard"])
        self.assertIn("accepted review", semantics["review_gate"])
        self.assertIn("does not write files", summary["boundary_notes"][3])
        self.assertIn("compatibility file writer", summary["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
