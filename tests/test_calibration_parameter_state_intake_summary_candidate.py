from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_parameter_state_intake import (
    build_calibration_parameter_state_intake_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_parameter_state_intake" / "basic_intake"


def _load_input() -> dict:
    return json.loads((FIXTURE / "intake-input.json").read_text(encoding="utf-8"))


class CalibrationParameterStateIntakeSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_parameter_state_intake_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-intake-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_parameter_state_intake_summary(source)

        source["managed_parameter_state"]["entries"][0]["value"] = {"mutated": ["value"]}
        source["managed_parameter_state"]["lineage"]["target_scope"].append("mutated")
        source["side_effect_claims"]["storage_mutation"] = "performed"

        self.assertEqual(summary["managed_parameter_state"]["entries"][0]["value"], 0.437)
        self.assertEqual(
            summary["managed_parameter_state"]["lineage"]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )
        self.assertEqual(summary["side_effects"]["storage_mutation"], "not_performed")

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["calibration_parameter_state_intake_policy"]["storage_writer"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_parameter_state_intake_summary(source)

    def test_nested_calibration_handoff_is_validated_first(self) -> None:
        source = _load_input()
        source["calibration_handoff_input"]["accepted_proposed_writes"][0]["apply_state"] = (
            "applied"
        )

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_parameter_state_intake_summary(source)

    def test_intake_requires_ready_handoff_request(self) -> None:
        source = _load_input()
        source["calibration_handoff_input"]["handoff_requests"][0]["request_state"] = (
            "blocked_missing_base_entry"
        )

        with self.assertRaisesRegex(ValueError, "handoff without review findings"):
            build_calibration_parameter_state_intake_summary(source)

    def test_review_must_be_accepted_and_match_handoff_request(self) -> None:
        source = _load_input()
        source["intake_review"]["review_status"] = "pending"

        with self.assertRaisesRegex(ValueError, "must be accepted"):
            build_calibration_parameter_state_intake_summary(source)

        source = _load_input()
        source["intake_review"]["source_handoff_review_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "source_handoff_review_id"):
            build_calibration_parameter_state_intake_summary(source)

        source = _load_input()
        source["intake_review"]["accepted_diff_paths"] = ["qubits.qA.drive_frequency_hz"]

        with self.assertRaisesRegex(ValueError, "accepted diff paths"):
            build_calibration_parameter_state_intake_summary(source)

    def test_managed_state_must_apply_handoff_diff_to_base_state(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["entries"][0]["value"] = 0.42

        with self.assertRaisesRegex(ValueError, "entry value"):
            build_calibration_parameter_state_intake_summary(source)

        source = _load_input()
        source["managed_parameter_state"]["entries"][1]["value"] = 5000000000

        with self.assertRaisesRegex(ValueError, "entry value"):
            build_calibration_parameter_state_intake_summary(source)

    def test_managed_state_must_preserve_handoff_and_base_provenance(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["entries"][0]["source_ids"] = [
            "base_parameter_state:param-state-0007"
        ]

        with self.assertRaisesRegex(ValueError, "entry source_ids"):
            build_calibration_parameter_state_intake_summary(source)

    def test_managed_state_lineage_and_review_identity_must_match(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["lineage"]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "lineage"):
            build_calibration_parameter_state_intake_summary(source)

        source = _load_input()
        source["managed_parameter_state"]["created_by_review_id"] = "review-other"

        with self.assertRaisesRegex(ValueError, "intake review"):
            build_calibration_parameter_state_intake_summary(source)

    def test_side_effect_claims_must_stay_out_of_scope(self) -> None:
        source = _load_input()
        source["side_effect_claims"]["hardware_write_back"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_write_back"):
            build_calibration_parameter_state_intake_summary(source)

        source = _load_input()
        source["side_effect_claims"]["durable_history"] = "written"

        with self.assertRaisesRegex(ValueError, "durable_history"):
            build_calibration_parameter_state_intake_summary(source)

    def test_trusted_paths_must_match_managed_entries(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["trusted_entry_paths"] = ["qubits.qA.pi_amp"]

        with self.assertRaisesRegex(ValueError, "trusted paths"):
            build_calibration_parameter_state_intake_summary(source)

    def test_duplicate_managed_entries_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["managed_parameter_state"]["entries"][0])
        duplicate["value"] = 5012500000
        duplicate["unit"] = "Hz"
        duplicate["source_ids"] = ["base_parameter_state:param-state-0007"]
        duplicate["change_source"] = "carried_forward_from_base_state"
        source["managed_parameter_state"]["entries"][1] = duplicate

        with self.assertRaisesRegex(ValueError, "duplicate path"):
            build_calibration_parameter_state_intake_summary(source)


if __name__ == "__main__":
    unittest.main()
