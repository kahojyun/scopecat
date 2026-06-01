from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_review_bundle import (
    build_calibration_review_bundle_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_review_bundle" / "basic_chain"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-bundle-input.json").read_text(encoding="utf-8"))


class CalibrationReviewBundleSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_review_bundle_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-bundle-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_builds_read_only_review_chain(self) -> None:
        summary = build_calibration_review_bundle_summary(_load_input())
        chain = summary["review_chain"][0]

        self.assertEqual(chain["step_record_id"], "step-record-rabi-qA-0001")
        self.assertEqual(chain["observation_link_ids"], ["observation-link-rabi-qA-07001"])
        self.assertEqual(chain["fit_result_ids"], ["fit-result-rabi-qA-0001"])
        self.assertEqual(chain["proposed_write_ids"], ["proposed-write-rabi-qA-pi-amp-0001"])
        self.assertEqual(chain["accepted_handoff_ids"], ["handoff-rabi-qA-pi-amp-0001"])
        self.assertEqual(chain["review_status"], "handoff_ready_without_parameter_state_intake")

    def test_bundle_does_not_start_parameter_state_intake(self) -> None:
        summary = build_calibration_review_bundle_summary(_load_input())
        handoff = summary["accepted_handoff_refs"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(handoff["parameter_state_intake_state"], "not_started")
        self.assertEqual(
            attention["parameter_state_intake_not_started"]["does_not_claim"],
            "parameter_state_draft_or_commit",
        )

    def test_missing_fit_result_is_review_finding_not_workflow_action(self) -> None:
        source = _load_input()
        source["fit_result_refs"] = []
        source["proposed_write_refs"][0]["evidence"]["fit_result_ids"] = []
        source["accepted_handoff_refs"] = []
        source["proposed_write_refs"] = []

        summary = build_calibration_review_bundle_summary(source)
        finding = summary["review_findings"][0]

        self.assertEqual(finding["finding"], "needs_fit_result_evidence")
        self.assertEqual(finding["does_not_claim"], "workflow_block_or_automatic_action")

    def test_pending_write_review_is_finding(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["review_state"] = "proposed_pending_review"
        source["accepted_handoff_refs"] = []

        summary = build_calibration_review_bundle_summary(source)

        self.assertEqual(summary["review_chain"][0]["review_status"], "needs_write_review")
        self.assertEqual(summary["review_findings"][0]["finding"], "needs_write_review")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_bundle_policy"]["parameter_state_intake"] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_state_intake"):
            build_calibration_review_bundle_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_bundle_policy"]["workflow_state_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_review_bundle_summary(source)

    def test_requires_every_child_summary_type(self) -> None:
        source = _load_input()
        source["child_summaries"].pop()

        with self.assertRaisesRegex(ValueError, "every child summary type"):
            build_calibration_review_bundle_summary(source)

    def test_child_summaries_must_not_be_rerun(self) -> None:
        source = _load_input()
        source["child_summaries"][0]["execution_posture"] = "rerun_by_bundle"

        with self.assertRaisesRegex(ValueError, "must not rerun"):
            build_calibration_review_bundle_summary(source)

    def test_observation_must_reference_known_step(self) -> None:
        source = _load_input()
        source["observation_links"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_review_bundle_summary(source)

    def test_fit_input_measurement_must_match_observation(self) -> None:
        source = _load_input()
        source["measurement_refs"].append(
            {
                "measurement_record_id": "measurement-07002",
                "label": "alternate",
                "experiment_type": "rabi_amplitude",
                "payload_owner": "measurement_records",
            }
        )
        source["fit_result_refs"][0]["input_refs"][0]["measurement_record_id"] = "measurement-07002"

        with self.assertRaisesRegex(ValueError, "must match observation link"):
            build_calibration_review_bundle_summary(source)

    def test_proposed_write_fit_evidence_must_reference_same_step(self) -> None:
        source = _load_input()
        source["review_steps"].append(
            {
                "step_record_id": "step-record-t1-qA-0001",
                "step_intent_id": "step-intent-t1-qA-0001",
                "label": "qA T1 review chain",
                "target": "qA",
                "context_resolution_state": "resolved_snapshot_recorded",
                "record_posture": "retrospective_step_record",
            }
        )
        source["fit_result_refs"][0]["step_record_id"] = "step-record-t1-qA-0001"

        with self.assertRaisesRegex(ValueError, "fit result input belongs"):
            build_calibration_review_bundle_summary(source)

    def test_handoff_requires_accepted_write(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["review_state"] = "proposed_pending_review"

        with self.assertRaisesRegex(ValueError, "accepted for parameter-state handoff"):
            build_calibration_review_bundle_summary(source)

    def test_handoff_must_not_start_intake(self) -> None:
        source = _load_input()
        source["accepted_handoff_refs"][0]["parameter_state_intake_state"] = "started"

        with self.assertRaisesRegex(ValueError, "intake must not start"):
            build_calibration_review_bundle_summary(source)

    def test_apply_claims_are_rejected(self) -> None:
        source = _load_input()
        source["proposed_write_refs"][0]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "not_applied"):
            build_calibration_review_bundle_summary(source)

    def test_duplicate_summary_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["child_summaries"][0])
        source["child_summaries"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate summary_id"):
            build_calibration_review_bundle_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_review_bundle_summary(source)

        source["review_steps"][0]["target"] = "mutated"
        source["proposed_write_refs"][0]["evidence"]["fit_result_ids"][0] = "mutated"
        source["accepted_handoff_refs"][0]["handoff_id"] = "mutated"

        self.assertEqual(summary["review_steps"][0]["target"], "qA")
        self.assertEqual(
            summary["proposed_write_refs"][0]["evidence"]["fit_result_ids"][0],
            "fit-result-rabi-qA-0001",
        )
        self.assertEqual(
            summary["accepted_handoff_refs"][0]["handoff_id"],
            "handoff-rabi-qA-pi-amp-0001",
        )


if __name__ == "__main__":
    unittest.main()
