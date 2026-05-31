from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.named_run_start_input_set import (
    build_named_run_start_input_set_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "named_run_start_input_set" / "basic_preparation"


def _load_input() -> dict:
    return json.loads((FIXTURE / "run-start-input-set-input.json").read_text(encoding="utf-8"))


class NamedRunStartInputSetSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_named_run_start_input_set_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-run-start-input-set-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_input_set_groups_family_owned_records_without_absorbing_payloads(self) -> None:
        summary = build_named_run_start_input_set_summary(_load_input())
        input_set = summary["run_start_input_sets"][0]
        refs = {ref["family"]: ref for ref in summary["selected_context_refs"]}

        self.assertEqual(input_set["input_set_id"], "run-start-inputs-chevron-qA-0001")
        self.assertEqual(input_set["context_ref_count"], 6)
        self.assertEqual(input_set["selected_context_count"], 5)
        self.assertEqual(
            set(refs),
            {
                "measurement_intent",
                "parameter_state",
                "setup_binding",
                "station_registry",
                "managed_code_version",
                "declared_environment",
            },
        )
        self.assertTrue(
            all(
                context["payload_handling"] == "family_owned_summary_only"
                for context in summary["context_records"]
            )
        )
        self.assertEqual(
            refs["managed_code_version"]["record_status"], "recorded_not_restore_contract"
        )

    def test_optional_unavailable_context_is_recorded_without_required_finding(self) -> None:
        summary = build_named_run_start_input_set_summary(_load_input())
        refs = {ref["family"]: ref for ref in summary["selected_context_refs"]}

        self.assertFalse(refs["declared_environment"]["required"])
        self.assertEqual(refs["declared_environment"]["include_state"], "unavailable")
        self.assertEqual(summary["missing_context_findings"], [])
        self.assertNotIn(
            "required_context_unavailable",
            [item["code"] for item in summary["attention"]],
        )

    def test_required_unavailable_context_is_a_finding_not_run_control(self) -> None:
        source = _load_input()
        source["run_start_input_sets"][0]["selected_contexts"][-1]["required"] = True

        summary = build_named_run_start_input_set_summary(source)
        finding = summary["missing_context_findings"][0]

        self.assertEqual(finding["family"], "declared_environment")
        self.assertEqual(finding["finding"], "required_context_unavailable")
        self.assertEqual(finding["does_not_claim"], "run_is_blocked_or_unsafe")
        self.assertIn(
            "required_context_unavailable",
            [item["code"] for item in summary["attention"]],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["run_start_input_policy"]["hardware_control"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_named_run_start_input_set_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["run_start_input_policy"]["restore_contract"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected policy shape"):
            build_named_run_start_input_set_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_named_run_start_input_set_summary(source)

        source["run_start_input_policy"]["shared_context_schema"] = "mutated"
        source["context_records"][0]["declared_summary"]["trusted_entry_count"] = 99
        source["run_start_input_sets"][0]["run_start_target"]["measurement_id"] = "mutated"

        self.assertEqual(summary["run_start_input_policy"]["shared_context_schema"], "not_defined")
        self.assertEqual(
            summary["context_records"][0]["declared_summary"]["trusted_entry_count"], 3
        )
        self.assertEqual(
            summary["run_start_input_sets"][0]["run_start_target"]["measurement_id"],
            "measurement-05001",
        )

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["context_records"][0])
        source["context_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_named_run_start_input_set_summary(source)

    def test_duplicate_input_set_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["run_start_input_sets"][0])
        source["run_start_input_sets"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate input_set_id"):
            build_named_run_start_input_set_summary(source)

    def test_selected_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["run_start_input_sets"][0]["selected_contexts"][1]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing selected context"):
            build_named_run_start_input_set_summary(source)

    def test_selected_context_family_must_match_context_record(self) -> None:
        source = _load_input()
        source["run_start_input_sets"][0]["selected_contexts"][1]["family"] = "setup_binding"

        with self.assertRaisesRegex(ValueError, "wrong family"):
            build_named_run_start_input_set_summary(source)

    def test_unavailable_required_context_needs_reason(self) -> None:
        source = _load_input()
        source["run_start_input_sets"][0]["selected_contexts"][-1]["required"] = True
        source["run_start_input_sets"][0]["selected_contexts"][-1].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "needs a reason"):
            build_named_run_start_input_set_summary(source)

    def test_non_selected_context_must_not_reference_context_record(self) -> None:
        source = _load_input()
        source["run_start_input_sets"][0]["selected_contexts"][-1]["context_id"] = (
            "managed-code-version-readout-0001"
        )

        with self.assertRaisesRegex(ValueError, "non-selected context"):
            build_named_run_start_input_set_summary(source)

    def test_boundary_output_keeps_execution_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-run-start-input-set-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "not a final context schema", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertEqual(
            candidate["run_start_input_policy"]["code_import_execution"], "not_performed"
        )
        self.assertEqual(
            attention["code_execution_not_granted"]["does_not_claim"],
            "execution_permission",
        )
        self.assertIn("Hardware control", expected["boundary_notes"][4])
        self.assertIn("code execution", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
