from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_sidecar_review_gui_state import (
    build_legacy_sidecar_review_gui_state_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_sidecar_review_gui_state" / "basic_view"


def _load_input() -> dict:
    return json.loads((FIXTURE / "gui-state-input.json").read_text(encoding="utf-8"))


def _action_ids(summary: dict) -> set[str]:
    return {action["action_id"] for action in summary["available_review_actions"]}


class LegacySidecarReviewGuiStateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_legacy_sidecar_review_gui_state_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-gui-state-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)
        self.assertNotIn("reference_semantics", summary)

    def test_ready_projection_exposes_cards_and_passive_actions(self) -> None:
        summary = build_legacy_sidecar_review_gui_state_summary(_load_input())
        cards = {card["card"]: card for card in summary["review_cards"]}
        actions = {action["action_id"]: action for action in summary["available_review_actions"]}

        self.assertEqual(summary["classification"], "legacy_sidecar_gui_ready")
        self.assertEqual(cards["lifecycle"]["lifecycle_state"], "completed")
        self.assertEqual(cards["legacy_locators"]["targets_with_available_locators"], 2)
        self.assertEqual(cards["primary_data"]["declared_preview_states"], ["degraded_preview"])
        self.assertEqual(
            cards["supporting_evidence"]["lifecycle_stages"], ["during_run", "run_start"]
        )
        self.assertIn("start_adapter_import_review", actions)
        self.assertEqual(actions["start_adapter_import_review"]["execution"], "not_performed")
        self.assertEqual(
            actions["start_adapter_import_review"]["does_not_claim"],
            "legacy_import_acceptance_or_adapter_execution",
        )

    def test_every_available_action_is_label_only_not_executed(self) -> None:
        summary = build_legacy_sidecar_review_gui_state_summary(_load_input())

        self.assertEqual(summary["action_posture"], "labels_only_not_executed")
        for action in summary["available_review_actions"]:
            self.assertEqual(action["execution"], "not_performed")
        self.assertEqual(summary["view_effects"]["action_execution"], "not_performed")
        self.assertEqual(summary["view_effects"]["run_blocking"], "not_claimed")

    def test_locator_attention_adds_locator_action_without_repair_claim(self) -> None:
        source = _load_input()
        review = source["legacy_sidecar_post_run_review_summary"]
        review["classification"] = "legacy_sidecar_post_run_needs_locator_review"
        review["source_sidecar"]["locator_review_classification"] = (
            "legacy_locator_review_insufficient"
        )
        review["review_sections"]["legacy_locators"]["classification"] = (
            "legacy_locator_review_insufficient"
        )
        review["review_sections"]["legacy_locators"]["targets"][0]["classification"] = (
            "locator_insufficient_operator_note_only"
        )
        review["review_findings"] = [
            {
                "code": "legacy_locator_operator_note_only",
                "severity": "review",
                "source_section": "legacy_locator_review",
                "basis": "Only operator-note locators are available.",
                "does_not_claim": "legacy_record_missing",
            }
        ]
        review["review_finding_count"] = 1

        summary = build_legacy_sidecar_review_gui_state_summary(source)
        actions = {action["action_id"]: action for action in summary["available_review_actions"]}
        locator_card = {card["card"]: card for card in summary["review_cards"]}["legacy_locators"]

        self.assertEqual(summary["classification"], "legacy_sidecar_gui_needs_locator_attention")
        self.assertIn("add_or_update_locator_note", actions)
        self.assertEqual(
            actions["add_or_update_locator_note"]["does_not_claim"],
            "reference_repair_or_backend_discovery",
        )
        self.assertIn(
            "legacy-sidecar-measurement-0001", locator_card["targets_needing_locator_review"]
        )
        self.assertEqual(summary["visible_findings"][0]["source_section"], "legacy_locator_review")

    def test_run_lifecycle_attention_is_visible_without_run_blocking(self) -> None:
        source = _load_input()
        review = source["legacy_sidecar_post_run_review_summary"]
        review["classification"] = "legacy_sidecar_post_run_failed_needs_review"
        review["review_sections"]["lifecycle"]["lifecycle"]["state"] = "failed"

        summary = build_legacy_sidecar_review_gui_state_summary(source)

        self.assertEqual(summary["classification"], "legacy_sidecar_gui_needs_run_attention")
        self.assertEqual(summary["view_effects"]["measurement_validity"], "not_claimed")
        self.assertEqual(summary["view_effects"]["run_blocking"], "not_claimed")

    def test_review_findings_are_visible_but_not_approval_gates(self) -> None:
        source = _load_input()
        review = source["legacy_sidecar_post_run_review_summary"]
        review["classification"] = "legacy_sidecar_post_run_needs_attention"
        review["review_findings"] = [
            {
                "code": "legacy_sidecar_manifest_note",
                "severity": "review",
                "source_section": "sidecar_manifest",
                "basis": "The legacy sidecar carried an operator note.",
                "does_not_claim": "measurement_invalid",
            }
        ]
        review["review_finding_count"] = 1

        summary = build_legacy_sidecar_review_gui_state_summary(source)

        self.assertEqual(summary["classification"], "legacy_sidecar_gui_needs_attention")
        self.assertEqual(summary["visible_findings"][0]["code"], "legacy_sidecar_manifest_note")
        self.assertIn("review_findings", _action_ids(summary))
        self.assertEqual(summary["view_effects"]["run_blocking"], "not_claimed")

    def test_gui_state_policy_positive_claims_are_rejected(self) -> None:
        source = _load_input()
        source["gui_state_policy"]["action_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "action_execution"):
            build_legacy_sidecar_review_gui_state_summary(source)

        source = _load_input()
        source["gui_state_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_legacy_sidecar_review_gui_state_summary(source)

    def test_extra_gui_state_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["gui_state_policy"]["workflow_gate"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_sidecar_review_gui_state_summary(source)

    def test_source_post_run_review_must_stay_read_only(self) -> None:
        source = _load_input()
        review_policy = source["legacy_sidecar_post_run_review_summary"][
            "sidecar_post_run_review_policy"
        ]
        review_policy["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            build_legacy_sidecar_review_gui_state_summary(source)

        source = _load_input()
        review_policy = source["legacy_sidecar_post_run_review_summary"][
            "sidecar_post_run_review_policy"
        ]
        review_policy["fresh_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "fresh_observation"):
            build_legacy_sidecar_review_gui_state_summary(source)

    def test_source_post_run_sections_and_counts_are_validated(self) -> None:
        source = _load_input()
        source["legacy_sidecar_post_run_review_summary"]["review_sections"].pop("primary_data")

        with self.assertRaisesRegex(ValueError, "sections"):
            build_legacy_sidecar_review_gui_state_summary(source)

        source = _load_input()
        source["legacy_sidecar_post_run_review_summary"]["review_finding_count"] = 9

        with self.assertRaisesRegex(ValueError, "review_finding_count"):
            build_legacy_sidecar_review_gui_state_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        source_copy = copy.deepcopy(source)
        summary = build_legacy_sidecar_review_gui_state_summary(source)

        source["legacy_sidecar_post_run_review_summary"]["review_sections"]["lifecycle"]["target"][
            "display"
        ] = "mutated"
        source["gui_state_policy"]["action_execution"] = "performed"

        self.assertEqual(
            summary["selected_measurement"]["target"],
            source_copy["legacy_sidecar_post_run_review_summary"]["review_sections"]["lifecycle"][
                "target"
            ],
        )
        self.assertEqual(summary["gui_state_policy"]["action_execution"], "not_performed")

    def test_boundary_output_keeps_gui_actions_and_import_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-gui-state-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("passive local GUI-state", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["view_effects"]["file_observation"], "not_performed")
        self.assertEqual(candidate["view_effects"]["legacy_import_acceptance"], "not_performed")
        self.assertEqual(
            attention["gui_actions_are_labels_only"]["does_not_claim"],
            "approval_gate_or_run_blocking",
        )
        self.assertIn("run-blocking review gate", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
