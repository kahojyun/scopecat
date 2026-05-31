from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.measurement_intent_resolution import (
    build_measurement_intent_resolution_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_intent_resolution" / "basic_resolution"


def _load_input() -> dict:
    return json.loads((FIXTURE / "intent-resolution-input.json").read_text(encoding="utf-8"))


class MeasurementIntentResolutionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_measurement_intent_resolution_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-intent-resolution-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_intent_selectors_are_distinct_from_recorded_context_links(self) -> None:
        summary = build_measurement_intent_resolution_summary(_load_input())
        selectors = summary["measurement_intent"]["moving_context_selectors"]
        links = summary["measurement_record"]["actual_context_links"]

        self.assertEqual(
            selectors[0]["reference_semantics"],
            "moving_reference",
        )
        self.assertEqual(
            links[0]["link_semantics"],
            "resolved_snapshot_used_at_run_start",
        )
        self.assertEqual(links[0]["context_id"], "param-state-0007")
        self.assertNotIn("selector_basis", links[0])

    def test_optional_unavailable_context_does_not_invalidate_record(self) -> None:
        summary = build_measurement_intent_resolution_summary(_load_input())
        finding = summary["optional_context_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(finding["family"], "declared_environment")
        self.assertEqual(finding["finding"], "optional_context_unavailable")
        self.assertEqual(finding["does_not_claim"], "measurement_record_invalid")
        self.assertEqual(
            summary["measurement_record"]["context_policy"],
            "context_optional_for_record_validity",
        )
        self.assertEqual(
            attention["context_optional_for_measurement_record"]["does_not_claim"],
            "context_required_for_primary_data_validity",
        )

    def test_post_run_lineage_movement_does_not_rewrite_record_context(self) -> None:
        summary = build_measurement_intent_resolution_summary(_load_input())
        movement = summary["lineage_movement_findings"][0]
        link = summary["measurement_record"]["actual_context_links"][0]

        self.assertEqual(movement["resolved_context_id"], "param-state-0007")
        self.assertEqual(movement["post_run_current_context_id"], "param-state-0008")
        self.assertEqual(
            movement["does_not_change"],
            "measurement_record_resolved_context_link",
        )
        self.assertEqual(link["context_id"], "param-state-0007")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["resolution_policy"]["hardware_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_measurement_intent_resolution_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["resolution_policy"]["restore_contract"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_measurement_intent_resolution_summary(source)

    def test_context_selectors_must_remain_optional_for_measurement_record(self) -> None:
        source = _load_input()
        source["measurement_intent"]["moving_context_selectors"][0][
            "required_for_measurement_record"
        ] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record"):
            build_measurement_intent_resolution_summary(source)

    def test_resolution_must_cover_every_selector(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["resolved_contexts"].pop()

        with self.assertRaisesRegex(ValueError, "cover every intent selector"):
            build_measurement_intent_resolution_summary(source)

    def test_resolution_intent_id_must_match_measurement_intent(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["intent_id"] = "other-intent"

        with self.assertRaisesRegex(ValueError, "intent_id"):
            build_measurement_intent_resolution_summary(source)

    def test_resolved_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "known context record"):
            build_measurement_intent_resolution_summary(source)

    def test_resolved_context_family_must_match_resolution_item(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = (
            "setup-binding-0002"
        )

        with self.assertRaisesRegex(ValueError, "family"):
            build_measurement_intent_resolution_summary(source)

    def test_unresolved_optional_context_needs_finding(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["resolved_contexts"][-1].pop("finding")

        with self.assertRaisesRegex(ValueError, "requires a finding"):
            build_measurement_intent_resolution_summary(source)

    def test_unresolved_optional_context_must_not_carry_context_id(self) -> None:
        source = _load_input()
        source["run_start_resolution"]["resolved_contexts"][-1]["resolved_context_id"] = (
            "param-state-0007"
        )

        with self.assertRaisesRegex(ValueError, "must not carry"):
            build_measurement_intent_resolution_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_measurement_intent_resolution_summary(source)

        source["measurement_intent"]["moving_context_selectors"][0]["selector_basis"][
            "lineage_id"
        ] = "mutated"
        source["measurement_record"]["primary_data"]["path"] = "mutated"
        source["run_start_resolution"]["resolved_contexts"][0]["resolved_context_id"] = "mutated"

        self.assertEqual(
            summary["measurement_intent"]["moving_context_selectors"][0]["selector_basis"][
                "lineage_id"
            ],
            "lineage-qA-default-bias",
        )
        self.assertEqual(
            summary["measurement_record"]["primary_data"]["path"],
            "records/measurement-05001/primary.csv",
        )
        self.assertEqual(
            summary["run_start_resolution"]["resolved_contexts"][0]["resolved_context_id"],
            "param-state-0007",
        )

    def test_duplicate_selector_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["measurement_intent"]["moving_context_selectors"][0])
        source["measurement_intent"]["moving_context_selectors"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate selector_id"):
            build_measurement_intent_resolution_summary(source)


if __name__ == "__main__":
    unittest.main()
