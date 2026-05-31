from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.parameter_trusted_drift_projection import (
    build_parameter_trusted_drift_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "parameter_trusted_drift_projection" / "basic_trusted_history"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "parameter-trusted-drift-input.json").read_text(encoding="utf-8"))


class ParameterTrustedDriftProjectionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_parameter_trusted_drift_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-parameter-trusted-drift-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_parameter_trusted_drift_summary(source)

        source["parameter_trusted_drift_policy"]["hardware_write_back"] = "performed"
        source["lineages"][0]["target_scope"].append("mutated")
        source["parameter_states"][1]["entries"][0]["value"] = {"mutated": ["value"]}

        self.assertEqual(summary["policy"]["hardware_write_back"], "not_performed")
        self.assertEqual(
            summary["lineages"][0]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )
        self.assertEqual(
            summary["drift_projections"][0]["path_series"][0]["points"][0]["value"],
            5012500000,
        )

    def test_duplicate_projection_ids_are_rejected(self) -> None:
        source = _load_input()
        source["drift_projections"].append(copy.deepcopy(source["drift_projections"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate projection_id"):
            build_parameter_trusted_drift_summary(source)

    def test_policy_must_keep_side_effects_out_of_scope(self) -> None:
        source = _load_input()
        source["parameter_trusted_drift_policy"]["drift_plot_rendering"] = "performed"

        with self.assertRaisesRegex(ValueError, "drift_plot_rendering"):
            build_parameter_trusted_drift_summary(source)

    def test_state_must_reference_known_lineage(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["lineage_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing lineage"):
            build_parameter_trusted_drift_summary(source)

    def test_included_state_must_be_committed_and_trusted(self) -> None:
        source = _load_input()
        source["parameter_states"][1]["state_kind"] = "seed_snapshot"

        with self.assertRaisesRegex(ValueError, "committed_snapshot"):
            build_parameter_trusted_drift_summary(source)

        source = _load_input()
        source["parameter_states"][1]["trust_status"] = "not_fully_trusted"

        with self.assertRaisesRegex(ValueError, "trusted for declared scope"):
            build_parameter_trusted_drift_summary(source)

    def test_included_state_requires_accepted_review_and_trusted_paths(self) -> None:
        source = _load_input()
        del source["parameter_states"][1]["accepted_review_id"]

        with self.assertRaisesRegex(ValueError, "accepted_review_id"):
            build_parameter_trusted_drift_summary(source)

        source = _load_input()
        source["parameter_states"][1]["trusted_entry_paths"] = []

        with self.assertRaisesRegex(ValueError, "trusted entry paths"):
            build_parameter_trusted_drift_summary(source)

    def test_trusted_entry_paths_must_exist_and_not_repeat(self) -> None:
        source = _load_input()
        source["parameter_states"][1]["trusted_entry_paths"].append("missing.entry")

        with self.assertRaisesRegex(ValueError, "trusts missing entry path"):
            build_parameter_trusted_drift_summary(source)

        source = _load_input()
        source["parameter_states"][1]["trusted_entry_paths"].append("qubits.qA.pi_amp")

        with self.assertRaisesRegex(ValueError, "duplicate trusted entry path"):
            build_parameter_trusted_drift_summary(source)

    def test_projection_must_stay_within_one_lineage(self) -> None:
        source = _load_input()
        source["lineages"].append(
            {
                "lineage_id": "lineage-other",
                "lineage_label": "other",
                "lineage_purpose": "working_point",
                "target_scope": ["sample-beta"],
            }
        )
        source["parameter_states"][3]["lineage_id"] = "lineage-other"

        with self.assertRaisesRegex(ValueError, "crosses parameter lineages"):
            build_parameter_trusted_drift_summary(source)

    def test_projection_paths_and_state_ids_must_be_explicit(self) -> None:
        source = _load_input()
        source["drift_projections"][0]["parameter_paths"] = []

        with self.assertRaisesRegex(ValueError, "requires parameter paths"):
            build_parameter_trusted_drift_summary(source)

        source = _load_input()
        source["drift_projections"][0]["state_ids"] = []

        with self.assertRaisesRegex(ValueError, "requires state_ids"):
            build_parameter_trusted_drift_summary(source)

    def test_untrusted_and_non_scalar_entries_are_review_findings(self) -> None:
        summary = build_parameter_trusted_drift_summary(_load_input())
        findings = summary["review_findings"]

        self.assertEqual(
            [finding["kind"] for finding in findings],
            [
                "excluded_state",
                "skipped_untrusted_entry",
                "missing_parameter_entry",
                "excluded_state",
                "skipped_untrusted_entry",
                "skipped_non_scalar_entry",
            ],
        )
        self.assertEqual(summary["drift_projections"][0]["path_series"][2]["point_count"], 0)
        self.assertEqual(summary["drift_projections"][0]["path_series"][3]["point_count"], 0)


if __name__ == "__main__":
    unittest.main()
