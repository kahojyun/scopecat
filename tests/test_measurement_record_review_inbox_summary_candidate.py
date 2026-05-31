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
OPERATOR_REVIEW_POLICY = {
    "catalog_authority": "record_local_projected_read_models",
    "running_inspection_authority": "caller_declared_running_inspection_requests",
    "selected_record_authority": "catalog_entry_or_running_inspection_summary",
    "storage_mutation": "not_performed",
    "record_discovery": "catalog_records_dir_only",
    "update_receipt_discovery": "not_performed",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "gui_state": "not_persisted",
}
OPERATOR_REVIEW_DOES_NOT_CLAIM = [
    "canonical_storage_authority",
    "record_repair",
    "read_model_refresh",
    "update_receipt_discovery",
    "primary_data_revalidation_beyond_child_operations",
    "lifecycle_finalization",
    "manifest_replacement",
    "storage_mutation",
    "gui_review_state",
    "public_export_schema",
]


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-inbox-input.json").read_text(encoding="utf-8"))


def _operator_review_payload(**overrides: object) -> dict:
    payload = {
        "artifact_posture": "local_measurement_record_operator_review",
        "operator_review_policy": copy.deepcopy(OPERATOR_REVIEW_POLICY),
        "workflow": {
            "classification": "measurement_record_operator_review_needed",
            "does_not_claim": list(OPERATOR_REVIEW_DOES_NOT_CLAIM),
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
    payload.update(overrides)
    return payload


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

    def test_visible_finding_cannot_be_marked_not_visible(self) -> None:
        source = _load_input()
        source["fresh_operator_review"]["review_findings"][0]["record_visibility"] = "not_visible"

        with self.assertRaisesRegex(ValueError, "visible review finding"):
            build_measurement_record_review_inbox_summary(source)

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

    def test_authority_looking_next_actions_are_rejected(self) -> None:
        source = _load_input()
        source["fresh_operator_review"]["review_findings"][0]["next_action"] = "approve_import"

        with self.assertRaisesRegex(ValueError, "review-only action"):
            build_measurement_record_review_inbox_summary(source)

    def test_projects_real_operator_review_shape_for_inbox(self) -> None:
        operator_review = _operator_review_payload()

        projected = project_operator_review_run_for_review_inbox(operator_review)

        self.assertEqual(projected["catalog_entries"][0]["label"], "run-3101-rabi")
        self.assertEqual(projected["review_findings"][0]["record_id"], "run-9999-needs-review")
        self.assertEqual(
            projected["review_findings"][0]["next_action"],
            "review_measurement_record_operator_findings",
        )

    def test_projects_missing_read_model_path_finding_as_not_visible(self) -> None:
        operator_review = _operator_review_payload(
            catalog={"entries": [], "review_findings": []},
            running_inspections=[],
            review_findings=[
                {
                    "code": "read_model_missing",
                    "source": "catalog",
                    "target": "records/run-9999-needs-review/record-read-model.json",
                    "message": "Record directory has no projected read model.",
                }
            ],
        )

        projected = project_operator_review_run_for_review_inbox(operator_review)

        self.assertEqual(projected["review_findings"][0]["record_id"], "run-9999-needs-review")
        self.assertEqual(projected["review_findings"][0]["record_visibility"], "not_visible")
        self.assertEqual(
            projected["review_findings"][0]["record_dir"],
            "records/run-9999-needs-review",
        )
        source = _load_input()
        source.pop("fresh_operator_review")
        source["operator_review"] = operator_review
        summary = build_measurement_record_review_inbox_summary(source)

        self.assertEqual(
            summary["inbox"]["lanes"]["needs_review"][0]["record_dir"],
            "records/run-9999-needs-review",
        )

    def test_projects_real_running_review_actions_for_inbox(self) -> None:
        for next_action in (
            "continue_monitoring_in_progress_record",
            "review_running_inspection_findings",
        ):
            with self.subTest(next_action=next_action):
                operator_review = _operator_review_payload(
                    running_inspections=[
                        {
                            "record": {
                                "record_id": "run-4101-t1",
                                "record_dir": "records/run-4101-t1",
                            },
                            "inspection": {
                                "visible_rows_recorded": 4,
                                "review_finding_codes": [],
                                "next_action": next_action,
                            },
                        }
                    ],
                    review_findings=[],
                )

                source = _load_input()
                source.pop("fresh_operator_review")
                source["operator_review"] = operator_review
                summary = build_measurement_record_review_inbox_summary(source)

                self.assertEqual(
                    summary["inbox"]["lanes"]["running"][0]["next_action"], next_action
                )

    def test_real_operator_review_overclaiming_policy_is_rejected(self) -> None:
        operator_review = _operator_review_payload()
        operator_review["operator_review_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "policy"):
            project_operator_review_run_for_review_inbox(operator_review)

    def test_real_operator_review_target_paths_are_validated(self) -> None:
        operator_review = _operator_review_payload()
        operator_review["review_findings"][0]["target"] = "records/run-9999-needs-review/../other"

        with self.assertRaisesRegex(ValueError, "relative"):
            project_operator_review_run_for_review_inbox(operator_review)

    def test_real_operator_review_non_visible_finding_projects_review_attention(
        self,
    ) -> None:
        operator_review = _operator_review_payload(
            request={
                "request_id": "operator-review-records",
                "selected_record_id": "missing-record",
            },
            catalog={"entries": [], "review_findings": []},
            running_inspections=[],
            review_findings=[
                {
                    "code": "selected_record_not_visible",
                    "target": "missing-record",
                    "message": "Selected record was not found.",
                }
            ],
        )
        source = _load_input()
        source.pop("fresh_operator_review")
        source["operator_review"] = operator_review

        summary = build_measurement_record_review_inbox_summary(source)

        self.assertEqual(
            summary["inbox"]["lanes"]["needs_review"][0]["record_id"], "missing-record"
        )
        self.assertEqual(
            summary["inbox"]["lanes"]["needs_review"][0]["record_visibility"],
            "not_visible",
        )

    def test_accepts_real_receipt_summary_shape_for_saved_receipts(self) -> None:
        source = _load_input()
        source["saved_receipt_summaries"] = [
            {
                "summary_schema": "scopecat.measurement_record_operator_review_receipt_summary.v0",
                "artifact_posture": "local_measurement_record_operator_review_receipt_summary",
                "summary_policy": {
                    "input_authority": "saved_operator_review_receipt",
                    "record_mutation": "not_performed",
                    "continuation_authority": "not_granted",
                    "gui_state": "not_persisted",
                    "redaction_boundary": "local_workspace_only",
                },
                "receipt": {
                    "request_id": "save-operator-review-records",
                    "review_receipt_path": "operator-reviews/review-001.json",
                    "operator_disposition": "recorded_for_continuation",
                    "operator_reason": "Continue later.",
                },
                "operator_review": {
                    "request_id": "operator-review-records",
                    "classification": "measurement_record_operator_review_needed",
                    "selected_record_id": "run-9999-needs-review",
                    "selected_record_source": "catalog",
                    "review_finding_codes": ["read_model_missing"],
                    "next_action": "review_measurement_record_operator_findings",
                },
                "does_not_claim": ["record_mutation"],
            }
        ]

        summary = build_measurement_record_review_inbox_summary(source)

        self.assertEqual(
            summary["inbox"]["lanes"]["continue_later"][0]["receipt_id"],
            "save-operator-review-records",
        )
        self.assertEqual(
            summary["inbox"]["lanes"]["continue_later"][0]["selected_record_source"],
            "catalog",
        )

    def test_accepts_real_receipt_summary_shape_without_selected_record(self) -> None:
        source = _load_input()
        source["saved_receipt_summaries"] = [
            {
                "summary_schema": "scopecat.measurement_record_operator_review_receipt_summary.v0",
                "artifact_posture": "local_measurement_record_operator_review_receipt_summary",
                "summary_policy": {
                    "input_authority": "saved_operator_review_receipt",
                    "record_mutation": "not_performed",
                    "continuation_authority": "not_granted",
                    "gui_state": "not_persisted",
                    "redaction_boundary": "local_workspace_only",
                },
                "receipt": {
                    "request_id": "save-operator-review-records",
                    "review_receipt_path": "operator-reviews/review-001.json",
                    "operator_disposition": "recorded_for_continuation",
                    "operator_reason": "Continue workspace review later.",
                },
                "operator_review": {
                    "request_id": "operator-review-records",
                    "classification": "measurement_record_operator_review_ready",
                    "selected_record_id": None,
                    "selected_record_source": None,
                    "review_finding_codes": [],
                    "next_action": "select_record_for_review",
                },
                "does_not_claim": ["record_mutation"],
            }
        ]

        summary = build_measurement_record_review_inbox_summary(source)

        self.assertIsNone(summary["inbox"]["lanes"]["continue_later"][0]["record_id"])
        self.assertEqual(
            summary["inbox"]["lanes"]["continue_later"][0]["record_visibility"],
            "not_selected",
        )
        self.assertIsNone(summary["inbox"]["lanes"]["continue_later"][0]["selected_record_source"])

    def test_saved_receipt_summary_path_must_use_receipt_namespace(self) -> None:
        source = _load_input()
        source["saved_receipt_summaries"][0]["review_receipt_path"] = (
            "records/run-3101-rabi/review.json"
        )

        with self.assertRaisesRegex(ValueError, "operator-reviews"):
            build_measurement_record_review_inbox_summary(source)


if __name__ == "__main__":
    unittest.main()
