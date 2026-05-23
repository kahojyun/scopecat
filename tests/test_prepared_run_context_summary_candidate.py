from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_context import (
    build_prepared_run_context_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_context" / "basic_preparation"


def _load_input() -> dict:
    return json.loads((FIXTURE / "prepared-run-context-input.json").read_text(encoding="utf-8"))


class PreparedRunContextSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_prepared_run_context_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-prepared-run-context-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_prepared_context_groups_selected_workspace_and_family_records(self) -> None:
        summary = build_prepared_run_context_summary(_load_input())
        prepared_context = summary["prepared_run_contexts"][0]
        refs = {ref["family"]: ref for ref in summary["selected_context_refs"]}

        self.assertEqual(
            prepared_context["prepared_run_context_id"],
            "prepared-run-context-chevron-qA-0001",
        )
        self.assertEqual(prepared_context["context_ref_count"], 7)
        self.assertEqual(prepared_context["selected_context_count"], 6)
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
        self.assertEqual(
            refs["editable_workspace_observation"]["record_status"],
            "observed_with_review_findings",
        )

    def test_workspace_observation_review_findings_are_not_readiness_claims(self) -> None:
        summary = build_prepared_run_context_summary(_load_input())
        finding = summary["workspace_context_findings"][0]

        self.assertEqual(finding["finding"], "workspace_observation_has_review_findings")
        self.assertEqual(
            finding["basis"],
            {
                "changed_observed": 1,
                "extra_observed": 1,
                "missing_expected": 1,
                "skipped_redacted": 1,
                "unavailable_reference": 1,
            },
        )
        self.assertEqual(finding["does_not_claim"], "run_is_blocked_or_workspace_is_unusable")

    def test_missing_required_context_is_a_finding_not_run_control(self) -> None:
        summary = build_prepared_run_context_summary(_load_input())
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
        source["prepared_run_context_policy"]["code_import_execution"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "code_import_execution"):
            build_prepared_run_context_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["prepared_run_context_policy"]["workspace_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected policy shape"):
            build_prepared_run_context_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_context_summary(source)

        source["prepared_run_context_policy"]["shared_context_schema"] = "mutated"
        source["context_records"][0]["declared_summary"]["logical_targets"].append("qB")
        source["prepared_run_contexts"][0]["manual_run_target"]["measurement_id"] = "mutated"

        self.assertEqual(
            summary["prepared_run_context_policy"]["shared_context_schema"],
            "not_defined",
        )
        self.assertEqual(
            summary["context_records"][0]["declared_summary"]["logical_targets"],
            ["qA", "cAB"],
        )
        self.assertEqual(
            summary["prepared_run_contexts"][0]["manual_run_target"]["measurement_id"],
            "measurement-05001",
        )

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["context_records"][0])
        source["context_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_prepared_run_context_summary(source)

    def test_duplicate_prepared_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["prepared_run_contexts"][0])
        source["prepared_run_contexts"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate prepared_run_context_id"):
            build_prepared_run_context_summary(source)

    def test_selected_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][1]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing selected context"):
            build_prepared_run_context_summary(source)

    def test_selected_context_family_must_match_context_record(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][1]["family"] = "setup_binding"

        with self.assertRaisesRegex(ValueError, "wrong family"):
            build_prepared_run_context_summary(source)

    def test_workspace_observation_must_align_to_selected_managed_version(self) -> None:
        source = _load_input()
        source["context_records"][5]["declared_summary"]["selected_version_id"] = (
            "managed-code-version-other"
        )

        with self.assertRaisesRegex(ValueError, "selected managed code version"):
            build_prepared_run_context_summary(source)

    def test_workspace_observation_requires_selected_managed_version(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"].pop(4)

        with self.assertRaisesRegex(ValueError, "requires selected managed code version"):
            build_prepared_run_context_summary(source)

    def test_selected_managed_version_requires_workspace_observation(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"].pop(5)

        with self.assertRaisesRegex(ValueError, "requires selected editable workspace"):
            build_prepared_run_context_summary(source)

    def test_manual_run_target_must_match_selected_measurement_intent(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["manual_run_target"]["experiment_label"] = (
            "different experiment"
        )

        with self.assertRaisesRegex(ValueError, "manual run target"):
            build_prepared_run_context_summary(source)

    def test_manual_run_target_alignment_fields_are_required(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["manual_run_target"].pop("entrypoint_hint")
        source["context_records"][0]["declared_summary"].pop("entrypoint_hint")

        with self.assertRaisesRegex(ValueError, "require field: entrypoint_hint"):
            build_prepared_run_context_summary(source)

    def test_unavailable_required_context_needs_reason(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][-1].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "needs a reason"):
            build_prepared_run_context_summary(source)

    def test_non_selected_context_must_not_reference_context_record(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][-1]["context_id"] = (
            "managed-code-version-readout-0001"
        )

        with self.assertRaisesRegex(ValueError, "non-selected context"):
            build_prepared_run_context_summary(source)

    def test_selected_context_must_not_carry_missing_reason(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][0]["missing_reason"] = None

        with self.assertRaisesRegex(ValueError, "selected context must not carry"):
            build_prepared_run_context_summary(source)

    def test_optional_not_selected_context_must_not_be_required(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][-1]["include_state"] = (
            "optional_not_selected"
        )

        with self.assertRaisesRegex(ValueError, "optional_not_selected"):
            build_prepared_run_context_summary(source)

    def test_boundary_output_keeps_execution_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-prepared-run-context-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "not a final run lifecycle",
            expected["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(
            candidate["prepared_run_context_policy"]["code_import_execution"],
            "not_performed",
        )
        self.assertEqual(
            attention["code_execution_not_granted"]["does_not_claim"],
            "execution_permission",
        )
        self.assertIn("Hardware control", expected["boundary_notes"][4])
        self.assertIn("code execution", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
