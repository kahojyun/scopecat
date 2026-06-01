from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_step_proposed_write_link import (
    build_calibration_step_proposed_write_link_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_step_proposed_write_link" / "basic_review"


def _load_input() -> dict:
    return json.loads((FIXTURE / "proposed-write-link-input.json").read_text(encoding="utf-8"))


class CalibrationStepProposedWriteLinkSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_step_proposed_write_link_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-proposed-write-link-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_proposed_write_links_step_record_to_parameter_lineage(self) -> None:
        summary = build_calibration_step_proposed_write_link_summary(_load_input())
        write = summary["proposed_writes"][0]

        self.assertEqual(write["step_record_id"], "step-record-rabi-qA-0001")
        self.assertEqual(
            write["target_parameter"]["lineage_id"],
            "lineage-qA-default-bias",
        )
        self.assertEqual(write["before_summary"]["context_id"], "param-state-0007")
        self.assertEqual(write["proposal_posture"], "pending_review_without_apply")

    def test_review_state_is_distinct_from_apply_state(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["review_state"] = "accepted_for_external_apply"

        summary = build_calibration_step_proposed_write_link_summary(source)
        write = summary["proposed_writes"][0]
        findings = summary["review_findings"]

        self.assertEqual(write["review_state"], "accepted_for_external_apply")
        self.assertEqual(write["apply_state"], "not_applied")
        self.assertEqual(
            write["proposal_posture"],
            "accepted_but_not_applied_by_this_slice",
        )
        self.assertEqual(findings[0]["does_not_claim"], "parameter_store_write")

    def test_rejected_write_still_has_no_apply(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["review_state"] = "rejected"

        summary = build_calibration_step_proposed_write_link_summary(source)

        self.assertEqual(
            summary["proposed_writes"][0]["proposal_posture"], "rejected_without_apply"
        )
        self.assertEqual(summary["proposed_writes"][0]["apply_state"], "not_applied")
        self.assertEqual(summary["review_findings"], [])

    def test_apply_claims_are_rejected(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["apply_state"] = "applied_to_parameter_store"

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["write_review_policy"]["parameter_store_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_store_write"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["write_review_policy"]["write_receipt"] = "created"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_proposed_write_must_reference_existing_step_record(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_before_context_must_be_known_parameter_context(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["before_summary"]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "known parameter context"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_before_context_must_be_linked_by_step_record(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["actual_context_links"] = [
            link
            for link in source["calibration_step_records"][0]["actual_context_links"]
            if link["family"] != "parameter_state"
        ]

        with self.assertRaisesRegex(ValueError, "linked by the step record"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_target_lineage_must_match_before_context(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["target_parameter"]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "target lineage"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_after_summary_must_not_claim_committed_context(self) -> None:
        source = _load_input()
        source["proposed_writes"][0]["after_summary"]["committed_context_id"] = "param-state-0008"

        with self.assertRaisesRegex(ValueError, "committed context"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_observation_refs_must_remain_reference_only(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["observation_link_refs"][0]["payload_handling"] = (
            "summary_projection"
        )

        with self.assertRaisesRegex(ValueError, "reference-only"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_duplicate_write_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["proposed_writes"][0])
        source["proposed_writes"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate write_id"):
            build_calibration_step_proposed_write_link_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_step_proposed_write_link_summary(source)

        source["proposed_writes"][0]["target_parameter"]["parameter_path"] = "mutated"
        source["proposed_writes"][0]["basis"]["observation_link_ids"][0] = "mutated"
        source["calibration_step_records"][0]["actual_context_links"][0]["context_id"] = "mutated"

        self.assertEqual(
            summary["proposed_writes"][0]["target_parameter"]["parameter_path"],
            "qA.drive.pi_pulse_amplitude",
        )
        self.assertEqual(
            summary["proposed_writes"][0]["basis"]["observation_link_ids"][0],
            "observation-link-rabi-qA-07001",
        )
        self.assertEqual(
            summary["calibration_step_records"][0]["actual_context_links"][0]["context_id"],
            "param-state-0007",
        )


if __name__ == "__main__":
    unittest.main()
