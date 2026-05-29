from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_continuation_route_shape import (
    build_calibration_continuation_route_shape_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_continuation_route_shape"
    / "minimum_contract_with_degraded_context"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "route-shape-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads((FIXTURE / "expected-route-shape-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class CalibrationContinuationRouteShapeSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_continuation_route_shape_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("gui_component", summary)
        self.assertNotIn("notebook_execution", summary)
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("measurement_payload", summary)
        self.assertNotIn("reference_payloads", summary)

    def test_minimum_contract_renders_with_degraded_context_attention(self) -> None:
        summary = build_calibration_continuation_route_shape_summary(_load_input())

        self.assertEqual(summary["route_shell"]["state"], "renderable_with_attention")
        self.assertEqual(
            summary["route_shell"]["minimum_contract_state"],
            "minimum_contract_satisfied_with_attention",
        )
        self.assertEqual(
            summary["context_panel"]["missing_support"][0]["input_id"],
            "route-input-setup-binding-08004",
        )
        self.assertEqual(
            summary["continuation_affordances"]["continuation_targets"],
            ["incident-rabi-visible-refit-07002"],
        )

    def test_no_signal_card_requires_remeasurement_before_dataset_selection(self) -> None:
        summary = build_calibration_continuation_route_shape_summary(_load_input())
        cards = {card["incident_id"]: card for card in summary["fit_recovery_lane"]["cards"]}

        no_signal = cards["incident-readout-no-signal-07001"]
        self.assertEqual(no_signal["route_state"], "requires_remeasurement")
        self.assertFalse(no_signal["can_continue"])
        self.assertFalse(no_signal["dataset_prompt"]["enabled"])
        self.assertEqual(
            summary["continuation_affordances"]["remeasurement_queue"],
            ["incident-readout-no-signal-07001"],
        )

    def test_visible_signal_refit_card_can_continue_and_prompt_dataset_add(self) -> None:
        summary = build_calibration_continuation_route_shape_summary(_load_input())
        cards = {card["incident_id"]: card for card in summary["fit_recovery_lane"]["cards"]}

        visible = cards["incident-rabi-visible-refit-07002"]
        self.assertTrue(visible["selected"])
        self.assertTrue(visible["can_continue"])
        self.assertTrue(visible["dataset_prompt"]["enabled"])
        self.assertTrue(visible["dataset_prompt"]["selected"])
        self.assertEqual(
            summary["continuation_affordances"]["dataset_add_prompts"],
            ["incident-rabi-visible-refit-07002"],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_continuation_route_shape_summary(source)

        source["route_input_contract_summary"]["route_context"]["target_group"] = "mutated"
        source["route_shape"]["cards"][1]["dataset_prompt"]["label"] = "mutated"

        self.assertEqual(summary["route_context"]["target_group"], "qA")
        self.assertEqual(
            summary["fit_recovery_lane"]["cards"][1]["dataset_prompt"]["label"],
            "Add failed and accepted refit pair",
        )

    def test_missing_minimum_contract_blocks_route_shape(self) -> None:
        source = _load_input()
        source["route_input_contract_summary"]["route_readiness"]["minimum_route_available"] = False

        with self.assertRaisesRegex(ValueError, "minimum route contract"):
            build_calibration_continuation_route_shape_summary(source)

    def test_selected_incident_must_match_fit_interaction_reference(self) -> None:
        source = _load_input()
        source["route_shape"]["selected_incident_id"] = "incident-readout-no-signal-07001"

        with self.assertRaisesRegex(ValueError, "selected incident"):
            build_calibration_continuation_route_shape_summary(source)

    def test_route_card_state_must_match_incident_specific_outcome(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][0]["route_state"] = "can_continue"
        source["route_input_contract_summary"]["input_contract"][1]["reference"][
            "incident_outcomes"
        ][0]["route_state"] = "requires_remeasurement"

        with self.assertRaisesRegex(ValueError, "route card state"):
            build_calibration_continuation_route_shape_summary(source)

    def test_route_card_incident_must_be_declared_by_fit_interaction(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][0]["incident_id"] = "incident-untracked-07009"

        with self.assertRaisesRegex(ValueError, "incident is not declared"):
            build_calibration_continuation_route_shape_summary(source)

    def test_remeasurement_card_cannot_offer_dataset_selection(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][0]["dataset_prompt"]["enabled"] = True

        with self.assertRaisesRegex(ValueError, "enabled flag"):
            build_calibration_continuation_route_shape_summary(source)

    def test_remeasurement_card_cannot_carry_selected_dataset_case(self) -> None:
        source = _load_input()
        prompt = source["route_shape"]["cards"][0]["dataset_prompt"]
        prompt["selected"] = True
        prompt["case_ref"] = "validation-case-should-not-exist"

        with self.assertRaisesRegex(ValueError, "selected flag"):
            build_calibration_continuation_route_shape_summary(source)

    def test_continuable_card_must_offer_dataset_prompt_in_fixture(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][1]["dataset_prompt"]["enabled"] = False

        with self.assertRaisesRegex(ValueError, "enabled flag"):
            build_calibration_continuation_route_shape_summary(source)

    def test_continuable_card_requires_lab_internal_case_reference(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][1]["dataset_prompt"]["case_ref"] = None

        with self.assertRaisesRegex(ValueError, "case reference"):
            build_calibration_continuation_route_shape_summary(source)

    def test_dataset_prompt_state_must_match_route_state(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][1]["dataset_prompt"]["state"] = "not_offered_remeasure_first"

        with self.assertRaisesRegex(ValueError, "prompt state"):
            build_calibration_continuation_route_shape_summary(source)

    def test_signal_classification_must_match_route_state(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][0]["signal_classification"] = "visible_signal"

        with self.assertRaisesRegex(ValueError, "signal classification"):
            build_calibration_continuation_route_shape_summary(source)

    def test_primary_action_must_match_route_state(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][0]["primary_user_action"]["action"] = (
            "continue_after_user_refit"
        )

        with self.assertRaisesRegex(ValueError, "primary action"):
            build_calibration_continuation_route_shape_summary(source)

    def test_rejects_nested_payload_fields(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][1]["fit_results"] = {"score": 0.9}

        with self.assertRaisesRegex(ValueError, "fit_results"):
            build_calibration_continuation_route_shape_summary(source)

    def test_rejects_unsupported_nested_route_card_fields(self) -> None:
        source = _load_input()
        source["route_shape"]["cards"][1]["dataset_prompt"]["handoff_ref"] = "handoff-001"

        with self.assertRaisesRegex(ValueError, "unsupported dataset prompt field"):
            build_calibration_continuation_route_shape_summary(source)

    def test_route_readiness_state_must_match_supporting_attention(self) -> None:
        source = _load_input()
        source["route_input_contract_summary"]["route_readiness"]["state"] = (
            "minimum_contract_satisfied"
        )

        with self.assertRaisesRegex(ValueError, "missing supporting inputs"):
            build_calibration_continuation_route_shape_summary(source)

    def test_route_context_current_step_must_match_continuation_reference(self) -> None:
        source = _load_input()
        source["route_input_contract_summary"]["input_contract"][0]["reference"][
            "current_step_id"
        ] = "step-mismatch"

        with self.assertRaisesRegex(ValueError, "current_step_id"):
            build_calibration_continuation_route_shape_summary(source)

    def test_policy_keeps_gui_rendering_not_performed(self) -> None:
        source = _load_input()
        source["route_shape_policy"]["gui_rendering"] = "performed"

        with self.assertRaisesRegex(ValueError, "gui_rendering"):
            build_calibration_continuation_route_shape_summary(source)


if __name__ == "__main__":
    unittest.main()
