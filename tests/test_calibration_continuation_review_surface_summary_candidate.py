from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_continuation_review_surface import (
    build_calibration_continuation_review_surface_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_continuation_review_surface" / "basic_surface"


def _load_input() -> dict:
    return json.loads((FIXTURE / "surface-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-surface-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class CalibrationContinuationReviewSurfaceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_calibration_continuation_review_surface_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_surface_state_prioritizes_backbone_blocks(self) -> None:
        summary = build_calibration_continuation_review_surface_summary(_load_input())

        self.assertEqual(summary["route_header"]["surface_state"], "blocked_with_context_findings")
        self.assertEqual(summary["backbone_findings_panel"]["blocked_case_count"], 1)

    def test_action_palette_is_labels_only(self) -> None:
        summary = build_calibration_continuation_review_surface_summary(_load_input())

        self.assertEqual(len(summary["action_palette"]), 6)
        self.assertEqual(
            {action["posture"] for action in summary["action_palette"]},
            {"labels_only_not_executed"},
        )
        self.assertNotIn("command", summary["action_palette"][0])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["surface_policy"]["notebook_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "notebook_execution"):
            build_calibration_continuation_review_surface_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["surface_policy"]["component_library"] = "defined"

        with self.assertRaisesRegex(ValueError, "policy shape"):
            build_calibration_continuation_review_surface_summary(source)

    def test_forbidden_gui_or_executable_keys_are_rejected(self) -> None:
        source = _load_input()
        source["review_state_summary"]["review_cards"][0]["command"] = "run_calibration"

        with self.assertRaisesRegex(ValueError, "command"):
            build_calibration_continuation_review_surface_summary(source)

    def test_selected_step_must_exist_in_review_cards(self) -> None:
        source = _load_input()
        source["surface_request"]["selected_step_id"] = "step-record-missing"

        with self.assertRaisesRegex(ValueError, "selected step"):
            build_calibration_continuation_review_surface_summary(source)

    def test_review_actions_must_remain_labels_only(self) -> None:
        source = _load_input()
        source["review_state_summary"]["review_cards"][0]["action_posture"] = "executable"

        with self.assertRaisesRegex(ValueError, "labels-only"):
            build_calibration_continuation_review_surface_summary(source)

    def test_backbone_context_must_preserve_parameter_state_identity(self) -> None:
        source = _load_input()
        source["backbone_context_summary"]["measurement_record_context"][
            "linked_parameter_state_id"
        ] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter-state identity"):
            build_calibration_continuation_review_surface_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_continuation_review_surface_summary(source)

        source["surface_request"]["selected_step_id"] = "mutated"
        source["review_state_summary"]["review_cards"][0]["available_review_actions"][0] = "mutated"
        source["backbone_findings_summary"]["review_findings"][0]["code"] = "mutated"

        self.assertEqual(summary["surface_request"]["selected_step_id"], "step-record-rabi-qA-0001")
        self.assertEqual(
            summary["step_review_lane"]["cards"][0]["available_review_actions"][0],
            "inspect_handoff",
        )
        self.assertEqual(
            summary["backbone_findings_panel"]["findings"][0]["code"],
            "parameter_state_intake_unavailable",
        )

    def test_duplicate_review_cards_are_rejected(self) -> None:
        source = _load_input()
        source["review_state_summary"]["review_cards"].append(
            copy.deepcopy(source["review_state_summary"]["review_cards"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate step_record_id"):
            build_calibration_continuation_review_surface_summary(source)


if __name__ == "__main__":
    unittest.main()
