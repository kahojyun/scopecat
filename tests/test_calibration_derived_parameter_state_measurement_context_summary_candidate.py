from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_derived_parameter_state_measurement_context import (
    build_calibration_derived_parameter_state_measurement_context_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_derived_parameter_state_measurement_context"
    / "basic_chain"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "route-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-route-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class CalibrationDerivedParameterStateMeasurementContextSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_calibration_derived_parameter_state_measurement_context_summary(
            _load_input()
        )

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_derived_parameter_state_measurement_context_summary(source)

        source["prepared_run_context_summary"]["manual_run_target"]["logical_targets"][0] = (
            "mutated"
        )
        source["measurement_context_link_summary"]["measurement_records"][0]["label"] = "mutated"

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(
            summary["measurement_record_context"]["measurement_label"],
            "qA chevron with calibration-derived parameter context",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["route_policy"]["hardware_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_handoff_must_preserve_calibration_observation(self) -> None:
        source = _load_input()
        source["accepted_write_handoff_summary"]["observation_measurement_record_id"] = (
            "measurement-other"
        )

        with self.assertRaisesRegex(ValueError, "observation measurement record"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_handoff_must_not_imply_apply(self) -> None:
        source = _load_input()
        source["accepted_write_handoff_summary"]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "hardware apply"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_intake_must_consume_accepted_handoff(self) -> None:
        source = _load_input()
        source["parameter_state_intake_summary"]["source_handoff"]["handoff_id"] = "handoff-other"

        with self.assertRaisesRegex(ValueError, "accepted handoff"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_prepared_run_must_select_managed_state(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["selected_context_refs"][1]["context_id"] = (
            "param-state-other"
        )

        with self.assertRaisesRegex(ValueError, "select"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_measurement_record_must_link_selected_parameter_state(self) -> None:
        source = _load_input()
        source["measurement_context_link_summary"]["linked_context_refs"][0]["context_id"] = (
            "param-state-other"
        )

        with self.assertRaisesRegex(ValueError, "measurement record"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_measurement_context_remains_optional(self) -> None:
        source = _load_input()
        source["measurement_context_link_summary"]["linked_context_refs"][0][
            "required_for_record_validity"
        ] = True

        with self.assertRaisesRegex(ValueError, "optional"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)

    def test_child_review_findings_make_route_need_review(self) -> None:
        source = _load_input()
        source["prepared_run_parameter_state_consumption_summary"]["review_findings"].append(
            {
                "code": "parameter_context_unavailable",
                "severity": "blocked",
                "basis": "Selected parameter-state snapshot was not available.",
            }
        )

        summary = build_calibration_derived_parameter_state_measurement_context_summary(source)

        self.assertEqual(
            summary["classification"],
            "calibration_derived_parameter_state_context_needs_review",
        )
        self.assertIn(
            "parameter_context_unavailable",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_duplicate_measurement_record_ids_are_rejected(self) -> None:
        source = _load_input()
        source["measurement_context_link_summary"]["measurement_records"].append(
            copy.deepcopy(source["measurement_context_link_summary"]["measurement_records"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate measurement_record_id"):
            build_calibration_derived_parameter_state_measurement_context_summary(source)


if __name__ == "__main__":
    unittest.main()
