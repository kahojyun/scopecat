from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_management" / "seed_review_commit"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "parameter-state-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-parameter-state-summary.json").read_text(encoding="utf-8")
    )


class ParameterStateManagementFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "parameter-state-input.json",
            FIXTURE / "expected-parameter-state-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_lineage_uses_working_point_as_purpose_not_generic_branch(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        lineage = summary["lineages"][0]

        self.assertEqual(lineage["lineage_id"], "lineage-qA-default-bias")
        self.assertEqual(lineage["lineage_purpose"], "working_point")
        self.assertEqual(lineage["purpose_kind"], "domain_label")
        self.assertEqual(lineage["lineage_purpose"], source["lineages"][0]["lineage_purpose"])

        encoded = json.dumps(summary)
        self.assertNotIn("generic_branch_model", encoded)

    def test_seed_state_is_not_treated_as_trusted_calibrated_truth(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        source_states = {state["state_id"]: state for state in source["parameter_states"]}
        states = {state["state_id"]: state for state in summary["states"]}

        seed = states["param-state-0001"]
        committed = states["param-state-0002"]

        self.assertEqual(seed["readiness"], "seeded_incomplete")
        self.assertEqual(seed["trust_status"], "not_fully_trusted")
        self.assertEqual(seed["history_plot_eligibility"], "exclude_from_trusted_drift_plots")
        self.assertEqual(seed["trusted_entry_paths"], [])

        self.assertEqual(committed["readiness"], "partially_calibrated")
        self.assertEqual(committed["trust_status"], "trusted_for_declared_scope")
        self.assertEqual(
            committed["history_plot_eligibility"],
            "include_declared_trusted_entries_only",
        )
        self.assertIn("qubits.qA.pi_amp", committed["trusted_entry_paths"])
        self.assertEqual(
            committed["trusted_entry_paths"],
            source_states["param-state-0002"]["trusted_entry_paths"],
        )

    def test_draft_is_not_durable_until_review_commit(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]

        self.assertFalse(summary["drafts"][0]["durable_history"])
        self.assertEqual(summary["drafts"][0]["draft_status"], "accepted_by_review")
        self.assertEqual(
            summary["drafts"][0]["draft_status"],
            source["draft_changes"][0]["draft_status"],
        )
        self.assertTrue(summary["reviewable_changes"][0]["creates_durable_history"])
        self.assertEqual(summary["reviewable_changes"][0]["review_status"], "accepted")
        self.assertEqual(summary["reviewable_changes"][0]["target_state_id"], "param-state-0002")

    def test_reviewable_diff_covers_changed_and_added_entries_without_schema_migration(
        self,
    ) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        change = summary["candidate_summary"]["reviewable_changes"][0]
        source_change = source["reviewable_diffs"][0]

        self.assertEqual(change["diff_counts"], {"changed": 2, "added": 1, "removed": 0})
        self.assertEqual(
            [entry["kind"] for entry in change["diff_entries"]],
            ["changed", "changed", "added"],
        )
        self.assertEqual(
            [entry["path"] for entry in change["diff_entries"]],
            [entry["path"] for entry in source_change["diff_entries"]],
        )
        self.assertIn("schema migration", summary["decisions_not_earned"])

    def test_measurement_reference_does_not_claim_current_hardware_state(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        reference = summary["measurement_references"][0]
        source_reference = source["measurements"][0]

        self.assertEqual(reference["measurement_id"], "measurement-03001")
        self.assertEqual(reference["selected_parameter_state_id"], "param-state-0002")
        self.assertEqual(reference["hardware_state_claim"], "not_recorded")
        self.assertEqual(
            reference["selected_parameter_state_id"],
            source_reference["selected_parameter_state_id"],
        )
        self.assertEqual(
            reference["hardware_state_claim"], source_reference["hardware_state_claim"]
        )

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-parameter-state-review.md").read_text(encoding="utf-8")

        self.assertIn("working_point` is a purpose label", review)
        self.assertIn("should not be plotted", review)
        self.assertIn("trusted calibrated truth", review)
        self.assertIn("not durable history", review)
        self.assertIn("by itself", review)
        self.assertIn("does not", review)
        self.assertIn("claim that Scopecat knows current instrument state", review)
        self.assertIn("external JSON overwrite behavior is evidence of current practice", review)


if __name__ == "__main__":
    unittest.main()
