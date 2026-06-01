from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_missing_evidence_findings import (
    build_calibration_missing_evidence_findings_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "calibration_missing_evidence_findings" / "basic_incomplete_chain"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "missing-evidence-input.json").read_text(encoding="utf-8"))


class CalibrationMissingEvidenceFindingsSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_missing_evidence_findings_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-missing-evidence-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_complete_step_stops_before_parameter_state_intake(self) -> None:
        summary = build_calibration_missing_evidence_findings_summary(_load_input())
        complete = {item["step_record_id"]: item for item in summary["evidence_completeness"]}[
            "step-record-rabi-qA-complete"
        ]

        self.assertEqual(complete["review_state"], "complete_until_parameter_state_intake")
        self.assertTrue(complete["has_accepted_write_handoff"])
        self.assertFalse(complete["finding_required"])

    def test_missing_observation_fit_pending_write_and_handoff_are_findings(self) -> None:
        summary = build_calibration_missing_evidence_findings_summary(_load_input())
        findings = {item["step_record_id"]: item["finding"] for item in summary["review_findings"]}

        self.assertEqual(
            findings["step-record-rabi-qB-missing-observation"],
            "missing_observation_evidence",
        )
        self.assertEqual(
            findings["step-record-rabi-qC-missing-fit"],
            "missing_fit_result_evidence",
        )
        self.assertEqual(findings["step-record-rabi-qD-failed-fit"], "fit_result_needs_review")
        self.assertEqual(
            findings["step-record-rabi-qE-pending-write"],
            "proposed_write_needs_review",
        )
        self.assertEqual(
            findings["step-record-rabi-qF-missing-handoff"],
            "accepted_write_handoff_missing",
        )

    def test_findings_do_not_decide_retry_or_continuation(self) -> None:
        summary = build_calibration_missing_evidence_findings_summary(_load_input())
        finding = summary["review_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            finding["does_not_claim"],
            "retry_remeasurement_continuation_or_write_back_decision",
        )
        self.assertEqual(
            attention["retry_remeasurement_not_decided"]["does_not_claim"],
            "retry_or_remeasurement_decision",
        )
        self.assertEqual(
            attention["continuation_decision_not_performed"]["does_not_claim"],
            "calibration_continuation_decision",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["missing_evidence_policy"]["retry_decision"] = "performed"

        with self.assertRaisesRegex(ValueError, "retry_decision"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["missing_evidence_policy"]["workflow_block"] = "computed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_observation_must_reference_known_step(self) -> None:
        source = _load_input()
        source["observation_links"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_observation_payload_must_remain_reference_only(self) -> None:
        source = _load_input()
        source["observation_links"][0]["payload_handling"] = "payload_read"

        with self.assertRaisesRegex(ValueError, "reference-only"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_fit_result_input_measurement_must_match_observation_link(self) -> None:
        source = _load_input()
        source["fit_result_refs"][0]["input_refs"][0]["measurement_record_id"] = (
            "measurement-qC-07003"
        )

        with self.assertRaisesRegex(ValueError, "must match observation link"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_fit_result_must_remain_declared_external_summary(self) -> None:
        source = _load_input()
        source["fit_result_refs"][0]["execution_posture"] = "executed_by_findings_slice"

        with self.assertRaisesRegex(ValueError, "declared external summary"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_proposed_write_evidence_must_reference_known_fit_result(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["evidence"]["fit_result_ids"] = ["missing"]

        with self.assertRaisesRegex(ValueError, "missing fit result"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_proposed_write_apply_claims_are_rejected(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_handoff_must_not_start_parameter_state_intake(self) -> None:
        source = _load_input()
        source["accepted_handoff_refs"][0]["parameter_state_intake_state"] = "started"

        with self.assertRaisesRegex(ValueError, "intake must not start"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_handoff_requires_accepted_write(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["review_state"] = "proposed_pending_review"

        with self.assertRaisesRegex(ValueError, "accepted for parameter-state handoff"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_duplicate_handoff_write_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["accepted_handoff_refs"][0])
        duplicate["handoff_id"] = "handoff-rabi-qA-duplicate"
        source["accepted_handoff_refs"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate handoff write_id"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_duplicate_step_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["review_steps"][0])
        source["review_steps"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate step_record_id"):
            build_calibration_missing_evidence_findings_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_missing_evidence_findings_summary(source)

        source["review_steps"][0]["target"] = "mutated"
        source["fit_result_refs"][0]["input_refs"][0]["observation_link_id"] = "mutated"
        source["accepted_handoff_refs"][0]["handoff_id"] = "mutated"

        self.assertEqual(summary["review_steps"][0]["target"], "qA")
        self.assertEqual(
            summary["fit_result_refs"][0]["input_refs"][0]["observation_link_id"],
            "observation-link-rabi-qA-07001",
        )
        self.assertEqual(
            summary["accepted_handoff_refs"][0]["handoff_id"],
            "handoff-rabi-qA-0001",
        )


if __name__ == "__main__":
    unittest.main()
