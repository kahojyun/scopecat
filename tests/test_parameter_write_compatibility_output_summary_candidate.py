from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.parameter_write_compatibility_output import (
    build_parameter_write_compatibility_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_write_compatibility_output" / "basic_output_plan"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "parameter-write-compatibility-input.json").read_text(encoding="utf-8")
    )


class ParameterWriteCompatibilityOutputSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_parameter_write_compatibility_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-parameter-write-compatibility-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_parameter_write_compatibility_summary(source)

        source["parameter_write_compatibility_policy"]["file_write"] = "performed"
        source["parameter_states"][0]["entries"][0]["value"] = {"mutated": ["value"]}

        self.assertEqual(summary["policy"]["file_write"], "not_performed")
        self.assertEqual(
            summary["compatibility_outputs"][0]["entries"][0]["value"],
            5012500000,
        )

    def test_duplicate_output_ids_are_rejected(self) -> None:
        source = _load_input()
        source["compatibility_outputs"].append(copy.deepcopy(source["compatibility_outputs"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate output_id"):
            build_parameter_write_compatibility_summary(source)

    def test_policy_must_keep_side_effects_out_of_scope(self) -> None:
        source = _load_input()
        source["parameter_write_compatibility_policy"]["hardware_write_back"] = "planned"

        with self.assertRaisesRegex(ValueError, "hardware_write_back"):
            build_parameter_write_compatibility_summary(source)

    def test_source_state_must_be_committed_and_trusted(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["state_kind"] = "seed_snapshot"

        with self.assertRaisesRegex(ValueError, "committed_snapshot"):
            build_parameter_write_compatibility_summary(source)

    def test_authorizing_review_must_be_accepted(self) -> None:
        source = _load_input()
        source["accepted_reviews"][0]["review_status"] = "pending"

        with self.assertRaisesRegex(ValueError, "accepted review"):
            build_parameter_write_compatibility_summary(source)

    def test_authorizing_review_must_target_source_state(self) -> None:
        source = _load_input()
        source["accepted_reviews"][0]["target_state_id"] = "missing-state"

        with self.assertRaisesRegex(ValueError, "references missing target state"):
            build_parameter_write_compatibility_summary(source)

    def test_source_state_review_must_be_source_state_accepted_review(self) -> None:
        source = _load_input()
        source["accepted_reviews"].append(
            {
                "review_id": "review-change-0002",
                "target_state_id": "param-state-0002",
                "review_status": "accepted",
                "creates_durable_history": True,
            }
        )
        source["compatibility_outputs"][0]["source_state_review_id"] = "review-change-0002"

        with self.assertRaisesRegex(ValueError, "accepted by source state"):
            build_parameter_write_compatibility_summary(source)

    def test_output_must_reference_known_source_state(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["source_state_id"] = "missing-state"

        with self.assertRaisesRegex(ValueError, "references missing source state"):
            build_parameter_write_compatibility_summary(source)

    def test_output_target_path_must_be_relative(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["target"]["path"] = "/tmp/parameters.json"

        with self.assertRaisesRegex(ValueError, "target path must be relative"):
            build_parameter_write_compatibility_summary(source)

    def test_output_claims_must_not_perform_file_writes(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["compatibility_claims"]["file_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "file_write"):
            build_parameter_write_compatibility_summary(source)

    def test_output_entries_must_account_for_every_source_entry(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["entries"] = source["compatibility_outputs"][0][
            "entries"
        ][:3]

        with self.assertRaisesRegex(ValueError, "account for every source entry"):
            build_parameter_write_compatibility_summary(source)

    def test_output_entries_must_not_repeat_source_entry_paths(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["compatibility_outputs"][0]["entries"][0])
        duplicate["output_key"] = "duplicate.key"
        source["compatibility_outputs"][0]["entries"][1] = duplicate

        with self.assertRaisesRegex(ValueError, "duplicate parameter entry path"):
            build_parameter_write_compatibility_summary(source)

    def test_planned_entries_must_be_trusted(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["entries"][3]["emit_state"] = "planned"
        source["compatibility_outputs"][0]["entries"][3]["output_key"] = "readout.qA.frequency_hz"

        with self.assertRaisesRegex(ValueError, "must be trusted"):
            build_parameter_write_compatibility_summary(source)

    def test_planned_entries_must_be_direct_scalar(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["entries"][4]["emit_state"] = "planned"
        source["compatibility_outputs"][0]["entries"][4]["output_key"] = (
            "readout.qA.calibration_table"
        )

        with self.assertRaisesRegex(ValueError, "direct scalar"):
            build_parameter_write_compatibility_summary(source)

    def test_planned_direct_scalar_entries_must_have_scalar_values(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["entries"][0]["value"] = ["not", "scalar"]

        with self.assertRaisesRegex(ValueError, "value must be scalar"):
            build_parameter_write_compatibility_summary(source)

    def test_trusted_entry_paths_must_not_repeat(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["trusted_entry_paths"].append("qubits.qA.pi_amp")

        with self.assertRaisesRegex(ValueError, "duplicate trusted entry path"):
            build_parameter_write_compatibility_summary(source)

    def test_schema_limited_skips_must_be_trusted(self) -> None:
        source = _load_input()
        source["parameter_states"][0]["trusted_entry_paths"].remove("readout.qA.calibration_table")

        with self.assertRaisesRegex(ValueError, "must be trusted"):
            build_parameter_write_compatibility_summary(source)

    def test_schema_limited_skips_must_match_table_shape(self) -> None:
        source = _load_input()
        source["compatibility_outputs"][0]["entries"][0]["emit_state"] = "skipped_schema_limited"
        source["compatibility_outputs"][0]["entries"][0]["reason"] = "not supported"

        with self.assertRaisesRegex(ValueError, "unsupported table shape"):
            build_parameter_write_compatibility_summary(source)


if __name__ == "__main__":
    unittest.main()
