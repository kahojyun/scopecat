from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "parameter_state_selection_context" / "known_good_future_context"
)


def _input_fixture() -> dict:
    return json.loads(
        (FIXTURE / "parameter-state-selection-input.json").read_text(encoding="utf-8")
    )


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-parameter-state-selection-summary.json").read_text(encoding="utf-8")
    )


class ParameterStateSelectionContextFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "parameter-state-selection-input.json",
            FIXTURE / "expected-parameter-state-selection-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_selection_is_context_input_reference_not_special_lifecycle(self) -> None:
        summary = _expected_summary()
        candidate = summary["candidate_summary"]
        selection = candidate["parameter_state_selections"][0]

        self.assertEqual(candidate["policy"]["selection_role"], "context_input_reference")
        self.assertEqual(selection["intent_role"], "scenario_label_not_lifecycle")
        self.assertEqual(selection["selection_intent_label"], "reuse_previous_working_state")
        self.assertIn(
            "not a special known-good lifecycle", summary["reference_semantics"]["selection_model"]
        )

    def test_context_owns_selected_state_requirement(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        context = candidate["selection_contexts"][0]
        selected_state = candidate["selected_states"][0]
        findings = candidate["review_findings"]

        self.assertEqual(
            context["required_selected_state"],
            "committed_trusted_for_declared_scope",
        )
        self.assertEqual(selected_state["state_kind"], "committed_snapshot")
        self.assertEqual(selected_state["trust_status"], "trusted_for_declared_scope")
        self.assertIn(
            "context_requirement_satisfied",
            [finding["kind"] for finding in findings],
        )

    def test_selection_does_not_claim_hardware_or_rollback_mutation(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        selection = candidate["parameter_state_selections"][0]

        self.assertEqual(selection["side_effects"]["hardware_write_back"], "not_performed")
        self.assertEqual(selection["side_effects"]["current_hardware_state_claim"], "not_claimed")
        self.assertEqual(selection["side_effects"]["rollback_mutation"], "not_performed")
        self.assertEqual(candidate["policy"]["branch_tag_commit_semantics"], "not_claimed")

    def test_structured_summary_states_fixture_boundary(self) -> None:
        summary = _expected_summary()
        semantics = summary["reference_semantics"]

        self.assertIn("not a final parameter schema", semantics["contract_guard"])
        self.assertIn("fixture scenario semantics", summary["boundary_notes"][1])
        self.assertIn("context-owned", summary["boundary_notes"][2])
        self.assertIn("rollback model", summary["decisions_not_earned"])
        self.assertIn("internal validation artifact", summary["boundary_notes"][4])


if __name__ == "__main__":
    unittest.main()
