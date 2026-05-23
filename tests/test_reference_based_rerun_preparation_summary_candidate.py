from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.reference_based_rerun_preparation import (
    build_reference_based_rerun_preparation_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reference_based_rerun_preparation" / "basic_rerun"


def _load_input() -> dict:
    return json.loads((FIXTURE / "rerun-preparation-input.json").read_text(encoding="utf-8"))


class ReferenceBasedRerunPreparationSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_reference_based_rerun_preparation_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-rerun-preparation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_reference_seed_groups_family_owned_context_without_claiming_goodness(self) -> None:
        summary = build_reference_based_rerun_preparation_summary(_load_input())
        selected_reference = summary["selected_reference_measurements"][0]
        rerun = summary["rerun_preparations"][0]
        refs = {ref["family"]: ref for ref in summary["selected_context_refs"]}

        self.assertEqual(
            selected_reference["selected_reference_id"],
            "selected-reference-rabi-qA-last-working",
        )
        self.assertEqual(selected_reference["context_ref_count"], 7)
        self.assertEqual(selected_reference["reference_claim"], "user_selected_reference_only")
        self.assertEqual(rerun["preparation_claim"], "manual_rerun_seed_summary_only")
        self.assertEqual(
            set(refs),
            {
                "measurement_intent",
                "parameter_state",
                "setup_binding",
                "station_registry",
                "managed_code_version",
                "editable_workspace_observation",
                "declared_environment",
            },
        )
        self.assertTrue(all(ref["seeded_from_reference_link"] for ref in refs.values()))

    def test_workspace_and_environment_findings_are_not_readiness_claims(self) -> None:
        summary = build_reference_based_rerun_preparation_summary(_load_input())
        workspace_finding = summary["workspace_context_findings"][0]
        environment_finding = summary["environment_context_findings"][0]

        self.assertEqual(
            workspace_finding["basis"],
            {
                "changed_observed": 1,
                "extra_observed": 1,
                "skipped_redacted": 1,
            },
        )
        self.assertEqual(
            workspace_finding["does_not_claim"],
            "run_is_blocked_or_workspace_is_unusable",
        )
        self.assertEqual(
            environment_finding["does_not_claim"],
            "environment_is_synced_runnable_or_reproducible",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["rerun_preparation_policy"]["reproducibility_claim"] = "guaranteed"

        with self.assertRaisesRegex(ValueError, "reproducibility_claim"):
            build_reference_based_rerun_preparation_summary(source)

    def test_positive_reference_claims_are_rejected(self) -> None:
        source = _load_input()
        source["selected_reference_measurements"][0]["reference_claim"] = (
            "scientifically_good_reference"
        )

        with self.assertRaisesRegex(ValueError, "selected reference claim"):
            build_reference_based_rerun_preparation_summary(source)

    def test_positive_preparation_claims_are_rejected(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["preparation_claim"] = "ready_to_execute"

        with self.assertRaisesRegex(ValueError, "rerun preparation claim"):
            build_reference_based_rerun_preparation_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["rerun_preparation_policy"]["executor"] = "available"

        with self.assertRaisesRegex(ValueError, "expected policy shape"):
            build_reference_based_rerun_preparation_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_reference_based_rerun_preparation_summary(source)

        source["rerun_preparation_policy"]["shared_context_schema"] = "mutated"
        source["context_records"][0]["declared_summary"]["logical_targets"].append("qB")
        source["rerun_preparations"][0]["proposed_run_target"]["measurement_id"] = "mutated"

        self.assertEqual(
            summary["rerun_preparation_policy"]["shared_context_schema"],
            "not_defined",
        )
        self.assertEqual(
            summary["context_records"][0]["declared_summary"]["logical_targets"],
            ["qA"],
        )
        self.assertEqual(
            summary["rerun_preparations"][0]["proposed_run_target"]["measurement_id"],
            "measurement-05021",
        )

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["context_records"][0])
        source["context_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_reference_based_rerun_preparation_summary(source)

    def test_duplicate_selected_reference_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["selected_reference_measurements"][0])
        source["selected_reference_measurements"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate selected_reference_id"):
            build_reference_based_rerun_preparation_summary(source)

    def test_duplicate_rerun_preparation_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["rerun_preparations"][0])
        source["rerun_preparations"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate rerun_preparation_id"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_preparation_must_reference_known_selected_reference(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_reference_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing selected reference"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_reference_measurement_must_match_selection(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["reference_measurement_id"] = "measurement-other"

        with self.assertRaisesRegex(ValueError, "reference measurement"):
            build_reference_based_rerun_preparation_summary(source)

    def test_selected_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_contexts"][1]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing selected context"):
            build_reference_based_rerun_preparation_summary(source)

    def test_selected_context_family_must_match_context_record(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_contexts"][1]["family"] = "setup_binding"

        with self.assertRaisesRegex(ValueError, "wrong family"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_context_must_be_seeded_from_reference_link(self) -> None:
        source = _load_input()
        alternate_context = copy.deepcopy(source["context_records"][1])
        alternate_context["context_id"] = "param-state-other"
        source["context_records"].append(alternate_context)
        source["rerun_preparations"][0]["selected_contexts"][1]["context_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "does not match reference link"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_cannot_invent_context_not_linked_by_reference(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_contexts"][1]["role"] = "alternate_values"

        with self.assertRaisesRegex(ValueError, "must carry"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_must_carry_reference_context_link_set(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_contexts"].pop()

        with self.assertRaisesRegex(ValueError, "must carry"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_required_flags_must_match_reference_links(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_contexts"][1]["required"] = False

        with self.assertRaisesRegex(ValueError, "required flag"):
            build_reference_based_rerun_preparation_summary(source)

    def test_rerun_missing_reason_must_match_reference_links(self) -> None:
        source = _load_input()
        unavailable_link = {
            "family": "declared_environment",
            "role": "runtime_environment_hint",
            "required": True,
            "include_state": "unavailable",
            "context_id": None,
            "missing_reason": "No reviewed declared environment record exists for reference.",
        }
        source["selected_reference_measurements"][0]["linked_contexts"][-1] = unavailable_link
        source["rerun_preparations"][0]["selected_contexts"][-1] = copy.deepcopy(unavailable_link)
        source["rerun_preparations"][0]["selected_contexts"][-1]["missing_reason"] = (
            "Different missing reason."
        )

        with self.assertRaisesRegex(ValueError, "missing_reason"):
            build_reference_based_rerun_preparation_summary(source)

    def test_workspace_observation_must_align_to_selected_managed_version(self) -> None:
        source = _load_input()
        source["context_records"][5]["declared_summary"]["selected_version_id"] = (
            "managed-code-version-other"
        )

        with self.assertRaisesRegex(ValueError, "selected managed code version"):
            build_reference_based_rerun_preparation_summary(source)

    def test_declared_environment_must_align_to_selected_managed_version(self) -> None:
        source = _load_input()
        source["context_records"][6]["declared_summary"]["managed_code_version_id"] = (
            "managed-code-version-other"
        )

        with self.assertRaisesRegex(ValueError, "declared environment context"):
            build_reference_based_rerun_preparation_summary(source)

    def test_proposed_target_must_match_selected_measurement_intent(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["proposed_run_target"]["experiment_label"] = (
            "different experiment"
        )

        with self.assertRaisesRegex(ValueError, "proposed run target"):
            build_reference_based_rerun_preparation_summary(source)

    def test_missing_required_reference_context_is_a_finding_not_run_control(self) -> None:
        source = _load_input()
        source["selected_reference_measurements"][0]["linked_contexts"][-1] = {
            "family": "declared_environment",
            "role": "runtime_environment_hint",
            "required": True,
            "include_state": "unavailable",
            "context_id": None,
            "missing_reason": "No reviewed declared environment record exists for reference.",
        }
        source["rerun_preparations"][0]["selected_contexts"][-1] = copy.deepcopy(
            source["selected_reference_measurements"][0]["linked_contexts"][-1]
        )
        source["context_records"] = [
            context
            for context in source["context_records"]
            if context["context_id"] != "declared-environment-rabi-0002"
        ]

        summary = build_reference_based_rerun_preparation_summary(source)
        finding = summary["missing_context_findings"][0]

        self.assertEqual(finding["family"], "declared_environment")
        self.assertEqual(finding["finding"], "required_reference_context_unavailable")
        self.assertEqual(
            finding["does_not_claim"],
            "run_is_blocked_or_reference_is_invalid",
        )
        self.assertIn(
            "required_reference_context_unavailable",
            [item["code"] for item in summary["attention"]],
        )

    def test_non_selected_context_must_not_reference_context_record(self) -> None:
        source = _load_input()
        source["selected_reference_measurements"][0]["linked_contexts"][-1]["include_state"] = (
            "unavailable"
        )
        source["rerun_preparations"][0]["selected_contexts"][-1]["include_state"] = "unavailable"

        with self.assertRaisesRegex(ValueError, "non-selected context"):
            build_reference_based_rerun_preparation_summary(source)

    def test_boundary_output_keeps_execution_and_reproducibility_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-rerun-preparation-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "not a final run lifecycle", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(
            candidate["rerun_preparation_policy"]["code_import_execution"],
            "not_performed",
        )
        self.assertEqual(
            candidate["rerun_preparation_policy"]["reproducibility_claim"],
            "not_made",
        )
        self.assertEqual(
            attention["reproducibility_not_claimed"]["does_not_claim"],
            "experiment_reproducible",
        )
        self.assertIn("Hardware control", expected["boundary_notes"][4])
        self.assertIn("code execution", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
