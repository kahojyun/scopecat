from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.measurement_record_review_inbox import (
    build_measurement_record_review_inbox_summary,
    project_operator_review_run_for_review_inbox,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_record_review_inbox" / "basic_workspace"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-inbox-input.json").read_text(encoding="utf-8"))


class MeasurementRecordReviewInboxSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_measurement_record_review_inbox_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-inbox-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_groups_current_records_and_saved_continuation_prompts(self) -> None:
        summary = build_measurement_record_review_inbox_summary(_load_input())
        inbox = summary["inbox"]

        self.assertEqual(inbox["classification"], "review_inbox_attention")
        self.assertEqual(
            inbox["counts"],
            {
                "continue_later": 1,
                "needs_review": 1,
                "reviewed": 0,
                "running": 1,
                "ready": 1,
            },
        )
        self.assertEqual(
            inbox["lanes"]["running"][0]["next_action"],
            "ready_for_later_finalization_decision",
        )
        self.assertEqual(
            inbox["lanes"]["continue_later"][0]["record_id"],
            "run-9999-needs-review",
        )

    def test_attention_does_not_grant_action_authority(self) -> None:
        summary = build_measurement_record_review_inbox_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            attention["saved_review_continuation_available"]["does_not_claim"],
            "retry_or_action_authority",
        )
        self.assertEqual(
            attention["records_need_review"]["does_not_claim"],
            "record_is_invalid_or_repairable",
        )
        self.assertIn("action_approval", summary["does_not_claim"])
        self.assertIn("canonical_gui_state", summary["does_not_claim"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_inbox_policy"]["record_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_mutation"):
            build_measurement_record_review_inbox_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_inbox_policy"]["dashboard_backend"] = "defined"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_measurement_record_review_inbox_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_measurement_record_review_inbox_summary(source)

        source["workspace"]["label"] = "mutated"
        source["fresh_operator_review"]["catalog_entries"][0]["label"] = "mutated"
        source["saved_receipt_summaries"][0]["operator_review"]["review_finding_codes"].append(
            "mutated"
        )

        self.assertEqual(summary["workspace"]["label"], "Local measurement review workspace")
        self.assertEqual(
            summary["inbox"]["lanes"]["ready"][0]["label"],
            "Rabi calibration complete",
        )
        self.assertEqual(
            summary["inbox"]["lanes"]["continue_later"][0]["review_finding_codes"],
            ["read_model_missing"],
        )

    def test_duplicate_visible_record_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["fresh_operator_review"]["catalog_entries"][0])
        source["fresh_operator_review"]["catalog_entries"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate visible record_id"):
            build_measurement_record_review_inbox_summary(source)

    def test_saved_receipt_missing_from_fresh_review_stays_visible_as_stale(
        self,
    ) -> None:
        source = _load_input()
        source["saved_receipt_summaries"][0]["operator_review"]["selected_record_id"] = (
            "run-missing"
        )

        summary = build_measurement_record_review_inbox_summary(source)

        self.assertEqual(
            summary["inbox"]["lanes"]["continue_later"][0]["record_visibility"],
            "not_visible",
        )

    def test_reviewed_receipt_does_not_create_attention_prompt(self) -> None:
        source = _load_input()
        source["saved_receipt_summaries"][0]["operator_disposition"] = "recorded_as_reviewed"

        summary = build_measurement_record_review_inbox_summary(source)

        self.assertEqual(summary["inbox"]["counts"]["continue_later"], 0)
        self.assertEqual(summary["inbox"]["counts"]["reviewed"], 1)
        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            ["records_need_review", "running_records_visible"],
        )

    def test_finding_must_reference_visible_record(self) -> None:
        source = _load_input()
        source["fresh_operator_review"]["review_findings"][0]["record_id"] = "run-missing"

        with self.assertRaisesRegex(ValueError, "visible record"):
            build_measurement_record_review_inbox_summary(source)

    def test_projects_real_operator_review_shape_for_inbox(self) -> None:
        operator_review = {
            "artifact_posture": "local_measurement_record_operator_review",
            "workflow": {
                "classification": "measurement_record_operator_review_needed",
            },
            "request": {
                "request_id": "operator-review-records",
                "selected_record_id": "run-4101-t1",
            },
            "catalog": {
                "entries": [
                    {
                        "record_id": "run-3101-rabi",
                        "record_dir": "records/run-3101-rabi",
                        "lifecycle_state": "complete",
                        "primary_data": {"observed_row_count": 5},
                        "review_finding_count": 0,
                    },
                    {
                        "record_id": "run-9999-needs-review",
                        "record_dir": "records/run-9999-needs-review",
                        "lifecycle_state": "complete",
                        "primary_data": {"observed_row_count": 3},
                        "review_finding_count": 1,
                    },
                ],
                "review_findings": [],
            },
            "running_inspections": [
                {
                    "record": {
                        "record_id": "run-4101-t1",
                        "record_dir": "records/run-4101-t1",
                    },
                    "inspection": {
                        "visible_rows_recorded": 5,
                        "review_finding_codes": [],
                        "next_action": "ready_for_later_finalization_decision",
                    },
                }
            ],
            "review_findings": [
                {
                    "code": "read_model_missing",
                    "source": "catalog",
                    "target": "records/run-9999-needs-review/record-read-model.json",
                    "message": "Record directory has no projected read model.",
                }
            ],
        }

        projected = project_operator_review_run_for_review_inbox(operator_review)

        self.assertEqual(projected["catalog_entries"][0]["label"], "run-3101-rabi")
        self.assertEqual(projected["review_findings"][0]["record_id"], "run-9999-needs-review")
        self.assertEqual(
            projected["review_findings"][0]["next_action"],
            "review_measurement_record_operator_findings",
        )


if __name__ == "__main__":
    unittest.main()
