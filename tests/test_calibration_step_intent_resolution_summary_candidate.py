from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_step_intent_resolution import (
    build_calibration_step_intent_resolution_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_step_intent_resolution" / "basic_resolution"


def _load_input() -> dict:
    return json.loads((FIXTURE / "step-intent-resolution-input.json").read_text(encoding="utf-8"))


class CalibrationStepIntentResolutionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_step_intent_resolution_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-step-intent-resolution-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_intent_selectors_are_distinct_from_step_record_context_links(self) -> None:
        summary = build_calibration_step_intent_resolution_summary(_load_input())
        selectors = summary["calibration_step_intent"]["moving_context_selectors"]
        links = summary["calibration_step_record"]["actual_context_links"]

        self.assertEqual(selectors[0]["reference_semantics"], "moving_reference")
        self.assertEqual(links[0]["link_semantics"], "resolved_snapshot_used_at_step_start")
        self.assertEqual(links[0]["context_id"], "param-state-0007")
        self.assertNotIn("selector_basis", links[0])

    def test_observation_links_remain_reference_only(self) -> None:
        summary = build_calibration_step_intent_resolution_summary(_load_input())
        refs = summary["calibration_step_record"]["observation_link_refs"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(refs[0]["link_id"], "observation-link-rabi-qA-07001")
        self.assertEqual(refs[0]["payload_handling"], "reference_only")
        self.assertEqual(
            attention["observation_links_are_reference_only"]["does_not_claim"],
            "measurement_payload_read",
        )

    def test_missing_optional_context_is_finding_not_blocking_or_write_back(self) -> None:
        summary = build_calibration_step_intent_resolution_summary(_load_input())
        finding = summary["optional_context_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(finding["family"], "declared_environment")
        self.assertEqual(finding["finding"], "optional_context_unavailable")
        self.assertEqual(finding["does_not_claim"], "calibration_step_invalid_or_blocked")
        self.assertEqual(
            attention["write_back_not_performed"]["does_not_claim"],
            "parameter_update",
        )

    def test_post_step_lineage_movement_does_not_rewrite_step_record(self) -> None:
        summary = build_calibration_step_intent_resolution_summary(_load_input())
        movement = summary["lineage_movement_findings"][0]
        link = summary["calibration_step_record"]["actual_context_links"][0]

        self.assertEqual(movement["resolved_context_id"], "param-state-0007")
        self.assertEqual(movement["post_step_current_context_id"], "param-state-0008")
        self.assertEqual(
            movement["does_not_change"],
            "calibration_step_record_resolved_context_link",
        )
        self.assertEqual(link["context_id"], "param-state-0007")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["resolution_policy"]["fit_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "fit_execution"):
            build_calibration_step_intent_resolution_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["resolution_policy"]["fit_quality_score"] = "computed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_step_intent_resolution_summary(source)

    def test_planned_observation_must_not_require_payload_reads(self) -> None:
        source = _load_input()
        source["calibration_step_intent"]["planned_observation"]["measurement_payload_required"] = (
            True
        )

        with self.assertRaisesRegex(ValueError, "payload reads"):
            build_calibration_step_intent_resolution_summary(source)

    def test_context_selectors_must_remain_optional_for_step_record(self) -> None:
        source = _load_input()
        source["calibration_step_intent"]["moving_context_selectors"][0][
            "required_for_step_record"
        ] = True

        with self.assertRaisesRegex(ValueError, "optional for step record"):
            build_calibration_step_intent_resolution_summary(source)

    def test_resolution_must_cover_every_selector(self) -> None:
        source = _load_input()
        source["step_start_resolution"]["resolved_contexts"].pop()

        with self.assertRaisesRegex(ValueError, "cover every step intent selector"):
            build_calibration_step_intent_resolution_summary(source)

    def test_resolved_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["step_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "known context record"):
            build_calibration_step_intent_resolution_summary(source)

    def test_resolved_context_family_must_match(self) -> None:
        source = _load_input()
        source["step_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = (
            "setup-binding-0002"
        )

        with self.assertRaisesRegex(ValueError, "family"):
            build_calibration_step_intent_resolution_summary(source)

    def test_unresolved_optional_context_needs_finding(self) -> None:
        source = _load_input()
        source["step_start_resolution"]["resolved_contexts"][-1].pop("finding")

        with self.assertRaisesRegex(ValueError, "requires a finding"):
            build_calibration_step_intent_resolution_summary(source)

    def test_observation_refs_must_remain_reference_only(self) -> None:
        source = _load_input()
        source["calibration_step_record"]["observation_link_refs"][0]["payload_handling"] = (
            "summary_projection"
        )

        with self.assertRaisesRegex(ValueError, "reference-only"):
            build_calibration_step_intent_resolution_summary(source)

    def test_duplicate_selector_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["calibration_step_intent"]["moving_context_selectors"][0])
        source["calibration_step_intent"]["moving_context_selectors"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate selector_id"):
            build_calibration_step_intent_resolution_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_step_intent_resolution_summary(source)

        source["calibration_step_intent"]["planned_observation"]["target"] = "mutated"
        source["step_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = "mutated"
        source["calibration_step_record"]["observation_link_refs"][0]["measurement_record_id"] = (
            "mutated"
        )

        self.assertEqual(
            summary["calibration_step_intent"]["planned_observation"]["target"],
            "qA",
        )
        self.assertEqual(
            summary["step_start_resolution"]["resolved_contexts"][0]["resolved_context_id"],
            "param-state-0007",
        )
        self.assertEqual(
            summary["calibration_step_record"]["observation_link_refs"][0]["measurement_record_id"],
            "measurement-07001",
        )


if __name__ == "__main__":
    unittest.main()
