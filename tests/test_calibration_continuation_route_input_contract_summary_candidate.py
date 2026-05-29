from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_continuation_route_input_contract import (
    build_calibration_continuation_route_input_contract_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_continuation_route_input_contract"
    / "minimum_render_with_missing_support"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "route-input-contract-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads(
        (FIXTURE / "expected-route-input-contract-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationContinuationRouteInputContractSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_continuation_route_input_contract_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("gui_component", summary)
        self.assertNotIn("notebook_execution", summary)
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("measurement_payload", summary)
        self.assertNotIn("reference_payloads", summary)

    def test_minimum_contract_is_satisfied_with_missing_supporting_inputs(self) -> None:
        summary = build_calibration_continuation_route_input_contract_summary(_load_input())
        contract = {item["input_id"]: item for item in summary["input_contract"]}

        self.assertEqual(
            summary["route_readiness"]["state"],
            "minimum_contract_satisfied_with_attention",
        )
        self.assertTrue(summary["route_readiness"]["minimum_route_available"])
        self.assertEqual(
            summary["route_readiness"]["missing_supporting_input_ids"],
            ["route-input-setup-binding-08004", "route-input-measurement-preview-08005"],
        )
        self.assertEqual(
            contract["route-input-work-continuation-08001"]["state"],
            "available",
        )
        self.assertEqual(
            contract["route-input-setup-binding-08004"]["state"],
            "missing_supporting_input",
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_continuation_route_input_contract_summary(source)

        source["route_context"]["target_group"] = "mutated"
        source["route_inputs"][0]["reference"]["step_ids"].append("mutated")

        self.assertEqual(summary["route_context"]["target_group"], "qA")
        self.assertNotIn("mutated", summary["input_contract"][0]["reference"]["step_ids"])

    def test_missing_minimum_family_is_rejected(self) -> None:
        source = _load_input()
        source["route_inputs"] = [
            item
            for item in source["route_inputs"]
            if item["family"] != "fit_recovery_interaction_summary"
        ]

        with self.assertRaisesRegex(ValueError, "missing minimum route input"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_unavailable_minimum_route_input_blocks_rendering(self) -> None:
        source = _load_input()
        route_input = source["route_inputs"][1]
        route_input["include_state"] = "unavailable"
        route_input.pop("reference")
        route_input["missing_reason"] = "Fit recovery interaction state is not available."

        summary = build_calibration_continuation_route_input_contract_summary(source)

        self.assertEqual(summary["route_readiness"]["state"], "minimum_contract_missing")
        self.assertEqual(
            summary["route_readiness"]["unavailable_minimum_input_ids"],
            ["route-input-fit-interaction-08002"],
        )
        self.assertEqual(summary["missing_context"][0]["severity"], "blocking")

    def test_reference_only_input_requires_reference(self) -> None:
        source = _load_input()
        source["route_inputs"][5].pop("reference")

        with self.assertRaisesRegex(ValueError, "requires reference"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_route_render_input_cannot_be_reference_only(self) -> None:
        source = _load_input()
        source["route_inputs"][1]["include_state"] = "reference_only"

        with self.assertRaisesRegex(ValueError, "route_render input cannot be reference_only"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_reference_context_input_must_remain_reference_only_or_unavailable(self) -> None:
        source = _load_input()
        source["route_inputs"][5]["include_state"] = "selected"

        with self.assertRaisesRegex(ValueError, "reference_context input"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_unavailable_reference_context_is_reported_as_attention(self) -> None:
        source = _load_input()
        route_input = source["route_inputs"][5]
        route_input["include_state"] = "unavailable"
        route_input.pop("reference")
        route_input["missing_reason"] = "Parameter state reference is not available."

        summary = build_calibration_continuation_route_input_contract_summary(source)

        self.assertIn(
            {
                "code": "route_reference_unavailable",
                "input_id": "route-input-parameter-state-08006",
                "family": "parameter_state_ref",
                "severity": "info",
                "message": "Parameter state reference is not available.",
                "does_not_claim": "route_blocked",
            },
            summary["attention"],
        )

    def test_unavailable_input_must_not_carry_reference(self) -> None:
        source = _load_input()
        source["route_inputs"][3]["reference"] = {"summary_id": "setup-binding-summary"}

        with self.assertRaisesRegex(ValueError, "must not carry reference"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_route_context_current_step_must_match_continuation_reference(self) -> None:
        source = _load_input()
        source["route_inputs"][0]["reference"]["current_step_id"] = "step-mismatch"

        with self.assertRaisesRegex(ValueError, "current_step_id does not match"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_route_input_rejects_nested_payload_fields(self) -> None:
        source = _load_input()
        source["route_inputs"][4]["measurement_payload"] = {"points": [1, 2, 3]}

        with self.assertRaisesRegex(ValueError, "unsupported route input field"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_optional_not_selected_must_be_optional_context(self) -> None:
        source = _load_input()
        source["route_inputs"][7]["required_for"] = "review_quality"

        with self.assertRaisesRegex(ValueError, "optional_not_selected input"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_policy_keeps_upstream_productization_not_required(self) -> None:
        source = _load_input()
        source["route_input_policy"]["upstream_productization_required"] = "required"

        with self.assertRaisesRegex(ValueError, "upstream_productization_required"):
            build_calibration_continuation_route_input_contract_summary(source)

    def test_unsupported_family_is_rejected(self) -> None:
        source = _load_input()
        source["route_inputs"][0]["family"] = "fit_runner_session"

        with self.assertRaisesRegex(ValueError, "unsupported route input family"):
            build_calibration_continuation_route_input_contract_summary(source)


if __name__ == "__main__":
    unittest.main()
