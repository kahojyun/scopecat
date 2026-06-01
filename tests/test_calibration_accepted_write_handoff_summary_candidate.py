from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_accepted_write_handoff import (
    build_calibration_accepted_write_handoff_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_accepted_write_handoff" / "basic_handoff"


def _load_input() -> dict:
    return json.loads((FIXTURE / "accepted-write-handoff-input.json").read_text(encoding="utf-8"))


class CalibrationAcceptedWriteHandoffSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_accepted_write_handoff_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-accepted-write-handoff-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_accepted_write_becomes_parameter_state_review_request(self) -> None:
        summary = build_calibration_accepted_write_handoff_summary(_load_input())
        write = summary["accepted_proposed_writes"][0]
        request = summary["handoff_requests"][0]

        self.assertEqual(write["review_state"], "accepted_for_parameter_state_handoff")
        self.assertEqual(write["apply_state"], "not_applied")
        self.assertEqual(request["target_route"], "parameter_state_management")
        self.assertEqual(
            request["reviewable_diff_request"]["diff_entries"][0]["path"],
            "qubits.qA.pi_amp",
        )
        self.assertEqual(request["does_not_claim"], "draft_created_or_committed_state")

    def test_handoff_does_not_commit_or_apply(self) -> None:
        summary = build_calibration_accepted_write_handoff_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            attention["parameter_state_route_owns_durable_history"]["does_not_claim"],
            "draft_created_or_review_accepted",
        )
        self.assertEqual(
            attention["apply_state_not_applied"]["does_not_claim"],
            "hardware_apply_or_parameter_store_write",
        )

    def test_blocked_handoff_is_review_finding_not_apply(self) -> None:
        source = _load_input()
        source["handoff_requests"][0]["request_state"] = "blocked_missing_base_entry"

        summary = build_calibration_accepted_write_handoff_summary(source)
        finding = summary["review_findings"][0]

        self.assertEqual(finding["finding"], "blocked_missing_base_entry")
        self.assertEqual(finding["does_not_claim"], "calibration_write_invalid_or_applied")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["handoff_policy"]["parameter_state_commit"] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_state_commit"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["handoff_policy"]["compatibility_file_write"] = "planned"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_write_must_be_accepted_for_handoff(self) -> None:
        source = _load_input()
        source["accepted_proposed_writes"][0]["review_state"] = "proposed_pending_review"

        with self.assertRaisesRegex(ValueError, "accepted_for_parameter_state_handoff"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_accepted_write_must_remain_not_applied(self) -> None:
        source = _load_input()
        source["accepted_proposed_writes"][0]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_before_context_must_be_linked_by_step_record(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["actual_context_links"] = []

        with self.assertRaisesRegex(ValueError, "linked by the step record"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_target_lineage_must_match_base_context(self) -> None:
        source = _load_input()
        source["accepted_proposed_writes"][0]["target_parameter"]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "target lineage"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_before_value_must_match_base_context_entry(self) -> None:
        source = _load_input()
        source["accepted_proposed_writes"][0]["before_summary"]["value"] = 0.41

        with self.assertRaisesRegex(ValueError, "before_summary value"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_handoff_diff_new_value_must_match_accepted_write(self) -> None:
        source = _load_input()
        source["handoff_requests"][0]["reviewable_diff_request"]["diff_entries"][0]["new_value"] = (
            0.44
        )

        with self.assertRaisesRegex(ValueError, "new value"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_handoff_leaves_durable_history_to_parameter_state_route(self) -> None:
        source = _load_input()
        source["handoff_requests"][0]["reviewable_diff_request"]["creates_durable_history"] = True

        with self.assertRaisesRegex(ValueError, "durable history"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_every_accepted_write_requires_handoff_request(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["accepted_proposed_writes"][0])
        duplicate["write_id"] = "proposed-write-rabi-qA-pi-amp-0002"
        source["accepted_proposed_writes"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "every accepted write"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_duplicate_handoff_write_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["handoff_requests"][0])
        duplicate["handoff_id"] = "handoff-rabi-qA-pi-amp-0002"
        source["handoff_requests"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate handoff write_id"):
            build_calibration_accepted_write_handoff_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_accepted_write_handoff_summary(source)

        source["accepted_proposed_writes"][0]["target_parameter"]["parameter_path"] = "mutated"
        source["handoff_requests"][0]["reviewable_diff_request"]["diff_entries"][0]["path"] = (
            "mutated"
        )
        source["calibration_step_records"][0]["actual_context_links"][0]["context_id"] = "mutated"

        self.assertEqual(
            summary["accepted_proposed_writes"][0]["target_parameter"]["parameter_path"],
            "qubits.qA.pi_amp",
        )
        self.assertEqual(
            summary["handoff_requests"][0]["reviewable_diff_request"]["diff_entries"][0]["path"],
            "qubits.qA.pi_amp",
        )
        self.assertEqual(
            summary["calibration_step_records"][0]["actual_context_links"][0]["context_id"],
            "param-context-0007",
        )


if __name__ == "__main__":
    unittest.main()
