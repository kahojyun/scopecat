from __future__ import annotations

import json
import unittest
from pathlib import Path

from scopecat.prepared_run import (
    PreparedRunAcknowledgement,
    PreparedRunAcknowledgementReviewRequest,
    PreparedRunReviewGateRequest,
    build_prepared_run_acknowledgement_summary,
    build_prepared_run_review_gate_summary,
    compose_prepared_run_acknowledgement_review,
    compose_prepared_run_review_gate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_review_gate" / "basic_gate"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-gate-input.json").read_text(encoding="utf-8"))


def _ack_item(area: str, index: int) -> dict:
    return {
        "acknowledgement_id": f"ack-review-item-{index}",
        "target": {"target_type": "review_item", "area": area},
        "actor_id": "operator-synthetic",
        "acknowledged_at": "2026-06-01T00:00:00Z",
        "acknowledgement_state": "acknowledged_for_manual_review_continuation",
        "note": f"Synthetic acknowledgement for {area}.",
    }


def _ack_finding(source_area: str, code: str, index: int) -> dict:
    return {
        "acknowledgement_id": f"ack-review-finding-{index}",
        "target": {
            "target_type": "review_finding",
            "source_area": source_area,
            "code": code,
        },
        "actor_id": "operator-synthetic",
        "acknowledged_at": "2026-06-01T00:00:00Z",
        "acknowledgement_state": "acknowledged_for_manual_review_continuation",
        "note": f"Synthetic acknowledgement for {source_area}:{code}.",
    }


def _acknowledge_all_non_ready_items_and_findings(gate_summary: dict) -> list[dict]:
    acknowledgements = []
    for item in gate_summary["review_items"]:
        if item["state"] != "ready_for_manual_review":
            acknowledgements.append(_ack_item(item["area"], len(acknowledgements)))
    for finding in gate_summary["aggregated_review_findings"]:
        acknowledgements.append(
            _ack_finding(
                finding["source_area"],
                finding["code"],
                len(acknowledgements),
            )
        )
    return acknowledgements


def _request_dict(gate_summary: dict, acknowledgements: list[dict]) -> dict:
    return {
        "acknowledgement_request": {
            "acknowledgement_review_id": "prepared-run-ack-review-chevron-qA-001"
        },
        "review_gate_summary": gate_summary,
        "acknowledgements": acknowledgements,
    }


def _source_without_required_context_block() -> dict:
    source = _load_input()
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    return source


class PreparedRunAcknowledgementPrototypeTest(unittest.TestCase):
    def test_acknowledges_non_required_gate_findings_for_manual_continuation(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgements = _acknowledge_all_non_ready_items_and_findings(gate_summary)

        summary = build_prepared_run_acknowledgement_summary(
            _request_dict(gate_summary, acknowledgements)
        )

        self.assertEqual(
            summary["continuation_decision"]["continuation_state"],
            "manual_review_acknowledged_for_continuation",
        )
        self.assertEqual(summary["continuation_decision"]["run_start_claim"], "not_claimed")
        self.assertEqual(summary["continuation_decision"]["hardware_control"], "not_performed")
        self.assertEqual(
            summary["continuation_decision"]["parameter_write_back"],
            "not_performed",
        )
        self.assertEqual(
            {item["acknowledgement_state"] for item in summary["review_item_acknowledgements"]},
            {"not_required", "acknowledged_for_manual_review_continuation"},
        )
        self.assertEqual(
            {finding["acknowledgement_state"] for finding in summary["finding_acknowledgements"]},
            {"acknowledged_for_manual_review_continuation"},
        )

    def test_typed_request_can_compose_over_gate_result(self) -> None:
        gate_result = compose_prepared_run_review_gate(
            PreparedRunReviewGateRequest.from_dict(_source_without_required_context_block())
        )
        acknowledgements = tuple(
            PreparedRunAcknowledgement.from_dict(acknowledgement)
            for acknowledgement in _acknowledge_all_non_ready_items_and_findings(
                gate_result.to_dict()
            )
        )

        request = PreparedRunAcknowledgementReviewRequest.from_gate_result(
            gate_result,
            acknowledgement_review_id="prepared-run-ack-review-chevron-qA-typed",
            acknowledgements=acknowledgements,
        )
        result = compose_prepared_run_acknowledgement_review(request)

        self.assertEqual(
            result.continuation_state,
            "manual_review_acknowledged_for_continuation",
        )
        self.assertEqual(
            result.to_dict()["acknowledgement_request"]["prepared_run_context_id"],
            gate_result.review_gate_request["prepared_run_context_id"],
        )

    def test_required_context_acknowledgement_does_not_unblock_required_context(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_load_input())
        acknowledgements = _acknowledge_all_non_ready_items_and_findings(gate_summary)

        summary = build_prepared_run_acknowledgement_summary(
            _request_dict(gate_summary, acknowledgements)
        )

        self.assertEqual(
            summary["source_review_gate"]["overall_state"],
            "blocked_by_required_context",
        )
        self.assertEqual(
            summary["continuation_decision"]["continuation_state"],
            "required_context_acknowledged_but_still_blocked",
        )
        self.assertEqual(
            summary["continuation_decision"]["recommended_action"],
            "repair_required_context_before_manual_pre_run_review",
        )
        self.assertEqual(summary["continuation_decision"]["readiness_claim"], "not_claimed")

    def test_missing_acknowledgements_keep_continuation_incomplete(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgements = [_ack_item("scope_alignment", 0)]

        summary = build_prepared_run_acknowledgement_summary(
            _request_dict(gate_summary, acknowledgements)
        )

        self.assertEqual(
            summary["continuation_decision"]["continuation_state"],
            "manual_review_acknowledgement_incomplete",
        )
        self.assertIn(
            "unacknowledged",
            {item["acknowledgement_state"] for item in summary["review_item_acknowledgements"]},
        )

    def test_ready_gate_needs_no_acknowledgement_for_manual_review_presentation(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["missing_context_findings"] = []
        source["prepared_run_context_summary"]["workspace_context_findings"] = []
        source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
        source["scope_alignment_summary"]["review_findings"] = []
        source["environment_review_summary"]["environment_review_findings"] = []
        gate_summary = build_prepared_run_review_gate_summary(source)

        summary = build_prepared_run_acknowledgement_summary(_request_dict(gate_summary, []))

        self.assertEqual(
            summary["continuation_decision"]["continuation_state"],
            "ready_for_manual_review",
        )
        self.assertEqual(
            {item["acknowledgement_state"] for item in summary["review_item_acknowledgements"]},
            {"not_required"},
        )

    def test_acknowledgement_target_must_reference_existing_gate_fact(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_load_input())
        acknowledgements = [_ack_finding("scope_alignment", "missing-code", 0)]

        with self.assertRaisesRegex(ValueError, "missing review finding"):
            build_prepared_run_acknowledgement_summary(
                _request_dict(gate_summary, acknowledgements)
            )

    def test_source_gate_must_keep_non_execution_boundary(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_load_input())
        gate_summary["gate_decision"]["environment_operation"] = "performed"

        with self.assertRaisesRegex(ValueError, "environment_operation"):
            build_prepared_run_acknowledgement_summary(_request_dict(gate_summary, []))

    def test_acknowledgement_summary_does_not_alias_gate_or_acknowledgement_input(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgements = _acknowledge_all_non_ready_items_and_findings(gate_summary)

        summary = build_prepared_run_acknowledgement_summary(
            _request_dict(gate_summary, acknowledgements)
        )
        gate_summary["review_gate_request"]["measurement_id"] = "mutated"
        acknowledgements[0]["note"] = "mutated"

        self.assertEqual(
            summary["acknowledgement_request"]["measurement_id"],
            "measurement-05001",
        )
        self.assertNotEqual(summary["acknowledgements"][0]["note"], "mutated")


if __name__ == "__main__":
    unittest.main()
