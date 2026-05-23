from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.parameter_state_management import (
    build_parameter_state_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_management" / "seed_review_commit"


def _load_input() -> dict:
    return json.loads((FIXTURE / "parameter-state-input.json").read_text(encoding="utf-8"))


class ParameterStateManagementSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_parameter_state_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-parameter-state-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_seed_and_committed_roles_preserve_parameter_boundary(self) -> None:
        summary = build_parameter_state_summary(_load_input())
        states = {state["state_id"]: state for state in summary["states"]}

        self.assertEqual(states["param-state-0001"]["role"], "base_seed_state")
        self.assertEqual(states["param-state-0001"]["trust_status"], "not_fully_trusted")
        self.assertEqual(states["param-state-0001"]["trusted_entry_paths"], [])
        self.assertEqual(states["param-state-0002"]["role"], "committed_parameter_state")
        self.assertEqual(
            states["param-state-0002"]["history_plot_eligibility"],
            "include_declared_trusted_entries_only",
        )

    def test_reviewable_diff_counts_changed_added_and_removed_entries(self) -> None:
        summary = build_parameter_state_summary(_load_input())
        review = summary["reviewable_changes"][0]

        self.assertEqual(review["diff_counts"], {"changed": 2, "added": 1, "removed": 0})
        self.assertEqual(
            [entry["kind"] for entry in review["diff_entries"]],
            ["changed", "changed", "added"],
        )
        self.assertNotIn("review_note", review["diff_entries"][0])

    def test_measurement_selection_does_not_claim_hardware_state(self) -> None:
        summary = build_parameter_state_summary(_load_input())
        reference = summary["measurement_references"][0]

        self.assertEqual(reference["selected_parameter_state_id"], "param-state-0002")
        self.assertEqual(reference["hardware_state_claim"], "not_recorded")
        self.assertEqual(summary["warnings"], [])

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_parameter_state_summary(source)

        source["lineages"][0]["target_scope"].append("mutated")
        source["parameter_states"][1]["trusted_entry_paths"].append("mutated")

        self.assertEqual(
            summary["lineages"][0]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )
        self.assertEqual(
            summary["states"][1]["trusted_entry_paths"],
            [
                "qubits.qA.drive_frequency_hz",
                "qubits.qA.pi_amp",
                "readout.qA.discrimination_threshold",
            ],
        )

    def test_duplicate_state_ids_are_rejected(self) -> None:
        source = _load_input()
        source["parameter_states"].append(copy.deepcopy(source["parameter_states"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate state_id"):
            build_parameter_state_summary(source)

    def test_state_must_reference_known_lineage(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["lineage_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing lineage"):
            build_parameter_state_summary(source)

    def test_parent_state_must_belong_to_same_lineage(self) -> None:
        source = _load_input()
        source["lineages"].append(
            {
                "lineage_id": "lineage-other",
                "lineage_label": "other",
                "lineage_purpose": "working_point",
                "target_scope": ["sample-alpha"],
                "purpose_note": "other",
            }
        )
        source["parameter_states"][1]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "parent belongs to wrong lineage"):
            build_parameter_state_summary(source)

    def test_trusted_entry_paths_must_exist_in_state_entries(self) -> None:
        source = _load_input()
        source["parameter_states"][1]["trusted_entry_paths"].append("missing.entry")

        with self.assertRaisesRegex(ValueError, "trusts missing entry path"):
            build_parameter_state_summary(source)

    def test_review_must_link_draft_base_and_target_state(self) -> None:
        source = _load_input()
        source["reviewable_diffs"][0]["target_state_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing target state"):
            build_parameter_state_summary(source)

    def test_accepted_review_must_be_linked_from_target_state(self) -> None:
        source = _load_input()
        source["parameter_states"][1]["accepted_review_id"] = "other-review"

        with self.assertRaisesRegex(ValueError, "not linked from target state"):
            build_parameter_state_summary(source)

    def test_measurement_must_reference_known_selected_state(self) -> None:
        source = _load_input()
        source["measurements"][0]["selected_parameter_state_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing parameter state"):
            build_parameter_state_summary(source)

    def test_hardware_state_claims_are_rejected(self) -> None:
        source = _load_input()
        source["measurements"][0]["hardware_state_claim"] = "applied"

        with self.assertRaisesRegex(ValueError, "hardware_state_claim"):
            build_parameter_state_summary(source)


if __name__ == "__main__":
    unittest.main()
