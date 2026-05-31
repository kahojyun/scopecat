from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.parameter_state_selection_context import (
    build_parameter_state_selection_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "parameter_state_selection_context" / "known_good_future_context"
)


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "parameter-state-selection-input.json").read_text(encoding="utf-8")
    )


class ParameterStateSelectionContextSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_parameter_state_selection_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-parameter-state-selection-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_parameter_state_selection_summary(source)

        source["parameter_state_selection_policy"]["hardware_write_back"] = "performed"
        source["lineages"][0]["target_scope"].append("mutated")
        source["selection_contexts"][0]["target_scope"].append("mutated")

        self.assertEqual(summary["policy"]["hardware_write_back"], "not_performed")
        self.assertEqual(
            summary["lineages"][0]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )
        self.assertEqual(
            summary["selection_contexts"][0]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )

    def test_duplicate_selection_ids_are_rejected(self) -> None:
        source = _load_input()
        source["parameter_state_selections"].append(
            copy.deepcopy(source["parameter_state_selections"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate selection_id"):
            build_parameter_state_selection_summary(source)

    def test_policy_must_keep_side_effects_out_of_scope(self) -> None:
        source = _load_input()
        source["parameter_state_selection_policy"]["rollback_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "rollback_mutation"):
            build_parameter_state_selection_summary(source)

    def test_state_must_reference_known_lineage(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["lineage_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing lineage"):
            build_parameter_state_selection_summary(source)

    def test_context_must_reference_known_lineage(self) -> None:
        source = _load_input()
        source["selection_contexts"][0]["lineage_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing lineage"):
            build_parameter_state_selection_summary(source)

    def test_selection_must_reference_known_context_and_state(self) -> None:
        source = _load_input()
        source["parameter_state_selections"][0]["context_id"] = "missing-context"

        with self.assertRaisesRegex(ValueError, "references missing context"):
            build_parameter_state_selection_summary(source)

        source = _load_input()
        source["parameter_state_selections"][0]["selected_state_id"] = "missing-state"

        with self.assertRaisesRegex(ValueError, "references missing state"):
            build_parameter_state_selection_summary(source)

    def test_selection_must_stay_within_context_lineage(self) -> None:
        source = _load_input()
        source["lineages"].append(
            {
                "lineage_id": "lineage-other",
                "lineage_label": "other",
                "lineage_purpose": "working_point",
                "target_scope": ["sample-beta"],
            }
        )
        source["parameter_states"][0]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "crosses parameter lineages"):
            build_parameter_state_selection_summary(source)

    def test_context_requirement_rejects_untrusted_selected_state(self) -> None:
        source = _load_input()
        source["parameter_state_selections"][0]["selected_state_id"] = "param-state-0003"

        with self.assertRaisesRegex(ValueError, "trusted selected state"):
            build_parameter_state_selection_summary(source)

    def test_selection_must_not_claim_hardware_or_rollback(self) -> None:
        source = _load_input()
        source["parameter_state_selections"][0]["hardware_write_back"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_write_back"):
            build_parameter_state_selection_summary(source)

        source = _load_input()
        source["parameter_state_selections"][0]["current_hardware_state_claim"] = "applied"

        with self.assertRaisesRegex(ValueError, "current hardware state"):
            build_parameter_state_selection_summary(source)

    def test_intent_label_is_review_fact_not_lifecycle(self) -> None:
        summary = build_parameter_state_selection_summary(_load_input())
        selection = summary["parameter_state_selections"][0]
        findings = summary["review_findings"]

        self.assertEqual(selection["selection_intent_label"], "reuse_previous_working_state")
        self.assertEqual(selection["intent_role"], "scenario_label_not_lifecycle")
        self.assertEqual(
            [finding["kind"] for finding in findings],
            ["intent_label_is_scenario_semantics", "context_requirement_satisfied"],
        )


if __name__ == "__main__":
    unittest.main()
