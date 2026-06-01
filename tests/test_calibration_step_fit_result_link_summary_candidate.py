from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_step_fit_result_link import (
    build_calibration_step_fit_result_link_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_step_fit_result_link" / "basic_reference"


def _load_input() -> dict:
    return json.loads((FIXTURE / "fit-result-link-input.json").read_text(encoding="utf-8"))


class CalibrationStepFitResultLinkSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_step_fit_result_link_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-fit-result-link-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_fit_result_links_observation_to_declared_estimate(self) -> None:
        summary = build_calibration_step_fit_result_link_summary(_load_input())
        fit_result = summary["fit_result_summaries"][0]

        self.assertEqual(fit_result["step_record_id"], "step-record-rabi-qA-0001")
        self.assertEqual(
            fit_result["input_refs"][0]["observation_link_id"],
            "observation-link-rabi-qA-07001",
        )
        self.assertEqual(
            fit_result["parameter_estimates"][0]["parameter_path"],
            "qA.drive.pi_pulse_amplitude",
        )
        self.assertEqual(fit_result["does_not_claim"], "fit_execution_or_write_acceptance")

    def test_proposed_write_refs_do_not_apply_writes(self) -> None:
        summary = build_calibration_step_fit_result_link_summary(_load_input())
        write_ref = summary["proposed_write_evidence_refs"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(write_ref["fit_result_refs"], ["fit-result-rabi-qA-0001"])
        self.assertEqual(write_ref["apply_state"], "not_applied")
        self.assertEqual(
            attention["proposed_write_decision_not_performed"]["does_not_claim"],
            "write_proposal_acceptance",
        )

    def test_failed_fit_result_becomes_review_finding_not_continuation_decision(self) -> None:
        source = _load_input()
        fit_result = source["fit_result_summaries"][0]
        fit_result["fit_state"] = "declared_failed"
        fit_result["review_state"] = "needs_human_review"

        summary = build_calibration_step_fit_result_link_summary(source)
        finding = summary["review_findings"][0]

        self.assertEqual(finding["finding"], "fit_result_needs_review")
        self.assertEqual(finding["does_not_claim"], "automatic_refit_remeasurement_or_write_block")
        self.assertEqual(
            summary["fit_result_summaries"][0]["fit_result_posture"],
            "declared_failure_needs_review",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["fit_result_link_policy"]["fit_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "fit_execution"):
            build_calibration_step_fit_result_link_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["fit_result_link_policy"]["fit_score_threshold"] = "accepted"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_step_fit_result_link_summary(source)

    def test_fit_result_must_reference_existing_step_record(self) -> None:
        source = _load_input()
        source["fit_result_summaries"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_step_fit_result_link_summary(source)

    def test_fit_input_must_reference_existing_observation_link(self) -> None:
        source = _load_input()
        source["fit_result_summaries"][0]["input_refs"][0]["observation_link_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing observation link"):
            build_calibration_step_fit_result_link_summary(source)

    def test_fit_input_observation_link_must_match_step_record(self) -> None:
        source = _load_input()
        source["calibration_step_records"].append(
            {
                "step_record_id": "step-record-t1-qA-0001",
                "step_intent_id": "step-intent-t1-qA-0001",
                "label": "qA T1 observed",
                "target": "qA",
                "record_state": "observation_linked",
                "observation_links": [
                    {
                        "link_id": "observation-link-t1-qA-07002",
                        "role": "review_evidence",
                        "observation_state": "linked",
                        "measurement_record_id": "measurement-07001",
                        "payload_handling": "summary_projection_only",
                    }
                ],
            }
        )
        source["fit_result_summaries"][0]["input_refs"][0]["observation_link_id"] = (
            "observation-link-t1-qA-07002"
        )

        with self.assertRaisesRegex(ValueError, "different step record"):
            build_calibration_step_fit_result_link_summary(source)

    def test_fit_input_measurement_must_match_observation_link(self) -> None:
        source = _load_input()
        source["measurement_record_summaries"].append(
            {
                "measurement_record_id": "measurement-07002",
                "label": "qA alternate measurement",
                "experiment_type": "rabi_amplitude",
                "target": "qA",
                "availability": "available",
                "preview_status": "preview_ready",
                "summary_authority": "measurement_record_summary",
                "primary_data_owner": "measurement_records",
            }
        )
        source["fit_result_summaries"][0]["input_refs"][0]["measurement_record_id"] = (
            "measurement-07002"
        )

        with self.assertRaisesRegex(ValueError, "must match observation link"):
            build_calibration_step_fit_result_link_summary(source)

    def test_fit_result_must_not_accept_estimate_for_write(self) -> None:
        source = _load_input()
        source["fit_result_summaries"][0]["parameter_estimates"][0]["accepted_for_write"] = True

        with self.assertRaisesRegex(ValueError, "accept estimates for write"):
            build_calibration_step_fit_result_link_summary(source)

    def test_proposed_write_ref_must_remain_not_applied(self) -> None:
        source = _load_input()
        source["proposed_write_evidence_refs"][0]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_step_fit_result_link_summary(source)

    def test_proposed_write_ref_must_reference_known_fit_result(self) -> None:
        source = _load_input()
        source["proposed_write_evidence_refs"][0]["fit_result_refs"] = ["missing"]

        with self.assertRaisesRegex(ValueError, "missing fit result"):
            build_calibration_step_fit_result_link_summary(source)

    def test_observation_links_must_remain_summary_projection_only(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["observation_links"][0]["payload_handling"] = (
            "payload_read"
        )

        with self.assertRaisesRegex(ValueError, "summary projection only"):
            build_calibration_step_fit_result_link_summary(source)

    def test_duplicate_fit_result_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["fit_result_summaries"][0])
        source["fit_result_summaries"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate fit_result_id"):
            build_calibration_step_fit_result_link_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_step_fit_result_link_summary(source)

        source["fit_result_summaries"][0]["parameter_estimates"][0]["parameter_path"] = "mutated"
        source["fit_result_summaries"][0]["declared_diagnostics"]["declared_quality_label"] = (
            "mutated"
        )
        source["proposed_write_evidence_refs"][0]["fit_result_refs"][0] = "mutated"

        self.assertEqual(
            summary["fit_result_summaries"][0]["parameter_estimates"][0]["parameter_path"],
            "qA.drive.pi_pulse_amplitude",
        )
        self.assertEqual(
            summary["fit_result_summaries"][0]["declared_diagnostics"]["declared_quality_label"],
            "reviewed_fit",
        )
        self.assertEqual(
            summary["proposed_write_evidence_refs"][0]["fit_result_refs"][0],
            "fit-result-rabi-qA-0001",
        )


if __name__ == "__main__":
    unittest.main()
