from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_backbone_context_findings import (
    build_calibration_backbone_context_findings_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_backbone_context_findings" / "basic_pressure"


def _load_input() -> dict:
    return json.loads((FIXTURE / "backbone-findings-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads(
        (FIXTURE / "expected-backbone-findings-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationBackboneContextFindingsSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_calibration_backbone_context_findings_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_ready_case_has_no_findings(self) -> None:
        summary = build_calibration_backbone_context_findings_summary(_load_input())
        cases = {case["case_id"]: case for case in summary["case_summaries"]}

        self.assertEqual(
            cases["ready-backbone"]["classification"], "calibration_backbone_context_ready"
        )
        self.assertEqual(cases["ready-backbone"]["finding_count"], 0)

    def test_blocked_and_review_findings_are_distinct(self) -> None:
        summary = build_calibration_backbone_context_findings_summary(_load_input())
        findings = {finding["case_id"]: finding for finding in summary["review_findings"]}

        self.assertEqual(findings["intake-unavailable"]["severity"], "blocked")
        self.assertEqual(
            findings["intake-unavailable"]["code"], "parameter_state_intake_unavailable"
        )
        self.assertEqual(findings["measurement-link-missing"]["severity"], "review")
        self.assertEqual(
            findings["measurement-link-missing"]["does_not_claim"], "measurement_record_invalid"
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["backbone_findings_policy"]["hardware_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_calibration_backbone_context_findings_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["backbone_findings_policy"]["route_repair"] = "performed"

        with self.assertRaisesRegex(ValueError, "policy shape"):
            build_calibration_backbone_context_findings_summary(source)

    def test_handoff_apply_claims_are_rejected(self) -> None:
        source = _load_input()
        source["backbone_cases"][0]["accepted_write_handoff"]["apply_state"] = "applied"

        with self.assertRaisesRegex(ValueError, "hardware apply"):
            build_calibration_backbone_context_findings_summary(source)

    def test_measurement_context_must_remain_optional(self) -> None:
        source = _load_input()
        source["backbone_cases"][0]["measurement_context_link"]["required_for_record_validity"] = (
            True
        )

        with self.assertRaisesRegex(ValueError, "optional"):
            build_calibration_backbone_context_findings_summary(source)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        source = _load_input()
        source["backbone_cases"].append(copy.deepcopy(source["backbone_cases"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            build_calibration_backbone_context_findings_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_backbone_context_findings_summary(source)

        source["backbone_findings_policy"]["hardware_control"] = "mutated"
        source["backbone_cases"][0]["label"] = "mutated"

        self.assertEqual(summary["backbone_findings_policy"]["hardware_control"], "not_performed")
        self.assertEqual(
            summary["case_summaries"][0]["label"],
            "Complete calibration-derived parameter context backbone",
        )


if __name__ == "__main__":
    unittest.main()
