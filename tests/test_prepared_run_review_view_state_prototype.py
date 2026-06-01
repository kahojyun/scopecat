from __future__ import annotations

import json
import unittest
from pathlib import Path

from scopecat.prepared_run import (
    PreparedRunAcknowledgement,
    PreparedRunAcknowledgementReviewRequest,
    PreparedRunReviewGateRequest,
    PreparedRunReviewViewStateRequest,
    build_prepared_run_acknowledgement_summary,
    build_prepared_run_review_gate_summary,
    build_prepared_run_review_view_state,
    compose_prepared_run_acknowledgement_review,
    compose_prepared_run_review_gate,
    project_prepared_run_review_view_state,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_review_gate" / "basic_gate"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-gate-input.json").read_text(encoding="utf-8"))


def _source_without_required_context_block() -> dict:
    source = _load_input()
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    return source


def _ready_source() -> dict:
    source = _load_input()
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    source["prepared_run_context_summary"]["workspace_context_findings"] = []
    source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
    source["scope_alignment_summary"]["review_findings"] = []
    source["environment_review_summary"]["environment_review_findings"] = []
    return source


def _ack_item(area: str, index: int) -> dict:
    return {
        "acknowledgement_id": f"view-state-ack-item-{index}",
        "target": {"target_type": "review_item", "area": area},
        "actor_id": "operator-synthetic",
        "acknowledged_at": "2026-06-01T00:00:00Z",
        "acknowledgement_state": "acknowledged_for_manual_review_continuation",
        "note": f"Synthetic acknowledgement for {area}.",
    }


def _ack_finding(source_area: str, code: str, index: int) -> dict:
    return {
        "acknowledgement_id": f"view-state-ack-finding-{index}",
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


def _acknowledgement_summary(gate_summary: dict) -> dict:
    return build_prepared_run_acknowledgement_summary(
        {
            "acknowledgement_request": {
                "acknowledgement_review_id": "prepared-run-view-state-ack-review-001"
            },
            "review_gate_summary": gate_summary,
            "acknowledgements": _acknowledge_all_non_ready_items_and_findings(gate_summary),
        }
    )


def _view_request_dict(
    gate_summary: dict,
    acknowledgement_summary: dict | None = None,
) -> dict:
    source = {
        "view_state_request": {"view_state_id": "prepared-run-review-view-chevron-qA-001"},
        "review_gate_summary": gate_summary,
    }
    if acknowledgement_summary is not None:
        source["acknowledgement_summary"] = acknowledgement_summary
    return source


class PreparedRunReviewViewStatePrototypeTest(unittest.TestCase):
    def test_projects_gate_summary_without_acknowledgements(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )

        view_state = build_prepared_run_review_view_state(_view_request_dict(gate_summary))

        self.assertEqual(view_state["header"]["presentation_state"], "needs_acknowledgement")
        self.assertEqual(view_state["header"]["acknowledgement_state"], "not_collected")
        self.assertEqual(
            [row["row_id"] for row in view_state["review_item_rows"]],
            [
                "review-item-00-required_context",
                "review-item-01-parameter_state",
                "review-item-02-scope_alignment",
                "review-item-03-workspace",
                "review-item-04-environment",
            ],
        )
        self.assertIn(
            "not_collected",
            {row["acknowledgement_state"] for row in view_state["finding_rows"]},
        )
        self.assertEqual(
            [label["action_id"] for label in view_state["next_action_labels"]],
            ["collect_acknowledgements", "review_findings"],
        )

    def test_projects_acknowledged_manual_review_state(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgement_summary = _acknowledgement_summary(gate_summary)

        view_state = build_prepared_run_review_view_state(
            _view_request_dict(gate_summary, acknowledgement_summary)
        )

        self.assertEqual(view_state["header"]["presentation_state"], "manual_review_acknowledged")
        self.assertEqual(
            view_state["header"]["acknowledgement_state"],
            "manual_review_acknowledged_for_continuation",
        )
        self.assertEqual(
            {row["acknowledgement_state"] for row in view_state["review_item_rows"]},
            {"not_required", "acknowledged_for_manual_review_continuation"},
        )
        self.assertEqual(
            {row["acknowledgement_state"] for row in view_state["finding_rows"]},
            {"acknowledged_for_manual_review_continuation"},
        )
        self.assertEqual(
            view_state["next_action_labels"],
            [
                {
                    "action_id": "continue_manual_review",
                    "label": "Continue manual review",
                    "action_kind": "label_only",
                    "execution": "not_performed",
                }
            ],
        )

    def test_required_context_remains_blocked_in_view_state_after_acknowledgement(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_load_input())
        acknowledgement_summary = _acknowledgement_summary(gate_summary)

        view_state = build_prepared_run_review_view_state(
            _view_request_dict(gate_summary, acknowledgement_summary)
        )

        self.assertEqual(view_state["header"]["gate_state"], "blocked_by_required_context")
        self.assertEqual(view_state["header"]["presentation_state"], "blocked_required_context")
        self.assertEqual(
            [label["action_id"] for label in view_state["next_action_labels"]],
            ["repair_required_context", "review_required_context"],
        )
        self.assertEqual(view_state["header"]["run_start_claim"], "not_claimed")

    def test_ready_gate_projects_ready_manual_review_header(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_ready_source())

        view_state = build_prepared_run_review_view_state(_view_request_dict(gate_summary))

        self.assertEqual(view_state["header"]["presentation_state"], "ready_for_manual_review")
        self.assertEqual(
            [label["action_id"] for label in view_state["next_action_labels"]],
            ["present_manual_review"],
        )
        self.assertEqual(
            {row["acknowledgement_state"] for row in view_state["review_item_rows"]},
            {"not_required"},
        )

    def test_typed_request_accepts_gate_result_and_acknowledgement_summary(self) -> None:
        gate_result = compose_prepared_run_review_gate(
            PreparedRunReviewGateRequest.from_dict(_source_without_required_context_block())
        )
        acknowledgements = tuple(
            PreparedRunAcknowledgement.from_dict(acknowledgement)
            for acknowledgement in _acknowledge_all_non_ready_items_and_findings(
                gate_result.to_dict()
            )
        )
        acknowledgement_summary = compose_prepared_run_acknowledgement_review(
            PreparedRunAcknowledgementReviewRequest.from_gate_result(
                gate_result,
                acknowledgement_review_id="prepared-run-view-state-ack-review-typed",
                acknowledgements=acknowledgements,
            )
        ).to_dict()

        request = PreparedRunReviewViewStateRequest.from_gate_result(
            gate_result,
            view_state_id="prepared-run-review-view-chevron-qA-typed",
            acknowledgement_summary=acknowledgement_summary,
        )
        result = project_prepared_run_review_view_state(request)

        self.assertEqual(result.presentation_state, "manual_review_acknowledged")
        self.assertEqual(
            result.to_dict()["view_state_request"]["prepared_run_context_id"],
            gate_result.review_gate_request["prepared_run_context_id"],
        )

    def test_view_state_preserves_data_projection_non_claims(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(_load_input())

        view_state = build_prepared_run_review_view_state(_view_request_dict(gate_summary))

        self.assertEqual(view_state["view_state_policy"]["gui_component"], "not_defined")
        self.assertEqual(view_state["view_state_policy"]["gui_persistence"], "not_performed")
        self.assertEqual(view_state["view_state_policy"]["action_execution"], "not_performed")
        self.assertEqual(view_state["view_state_policy"]["automatic_run_start"], "not_performed")
        self.assertEqual(view_state["view_state_policy"]["portable_export"], "not_performed")
        self.assertEqual(view_state["header"]["hardware_control"], "not_performed")
        self.assertEqual(view_state["header"]["parameter_write_back"], "not_performed")
        self.assertEqual(view_state["header"]["environment_operation"], "not_performed")
        self.assertEqual(view_state["header"]["code_import_execution"], "not_performed")

    def test_acknowledgement_summary_must_match_gate_summary(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgement_summary = _acknowledgement_summary(gate_summary)
        acknowledgement_summary["acknowledgement_request"]["measurement_id"] = "other-measurement"

        with self.assertRaisesRegex(ValueError, "measurement_id"):
            build_prepared_run_review_view_state(
                _view_request_dict(gate_summary, acknowledgement_summary)
            )

    def test_view_state_does_not_alias_inputs_or_outputs(self) -> None:
        gate_summary = build_prepared_run_review_gate_summary(
            _source_without_required_context_block()
        )
        acknowledgement_summary = _acknowledgement_summary(gate_summary)

        view_state = build_prepared_run_review_view_state(
            _view_request_dict(gate_summary, acknowledgement_summary)
        )
        gate_summary["prepared_run_context"]["label"] = "mutated"
        acknowledgement_summary["review_item_acknowledgements"][0]["acknowledgement_state"] = (
            "mutated"
        )
        view_state["review_item_rows"][0]["state"] = "mutated"

        rebuilt = build_prepared_run_review_view_state(
            _view_request_dict(
                build_prepared_run_review_gate_summary(_source_without_required_context_block()),
                _acknowledgement_summary(
                    build_prepared_run_review_gate_summary(_source_without_required_context_block())
                ),
            )
        )
        self.assertEqual(rebuilt["header"]["label"], "qA chevron manual run context")
        self.assertNotEqual(rebuilt["review_item_rows"][0]["state"], "mutated")


if __name__ == "__main__":
    unittest.main()
