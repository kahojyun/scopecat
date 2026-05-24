from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.environment_comparison import (
    build_environment_comparison_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "environment_comparison" / "basic_declared_context_compare"


def _load_input() -> dict:
    return json.loads((FIXTURE / "environment-comparison-input.json").read_text(encoding="utf-8"))


class EnvironmentComparisonSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_environment_comparison_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-environment-comparison-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_comparison_reports_expected_objective_findings(self) -> None:
        summary = build_environment_comparison_summary(_load_input())
        findings = {
            (item["fact_type"], item["fact_id"]): item
            for item in summary["environment_fact_findings"]
        }

        self.assertEqual(
            findings[("modern_python_environment", "manager")]["finding"],
            "same_declared",
        )
        self.assertEqual(
            findings[("modern_python_environment", "lockfile_path")]["finding"],
            "changed",
        )
        self.assertEqual(findings[("dependency_group", "analysis")]["finding"], "missing")
        self.assertEqual(findings[("dependency_group", "calibration")]["finding"], "missing")
        self.assertEqual(
            findings[("external_runtime_note", "external-vna-driver")]["finding"],
            "unverified",
        )
        self.assertEqual(
            findings[("migration_note", "legacy-qcodes-pin")]["finding"],
            "unsupported",
        )

    def test_comparison_counts_findings_without_readiness_claims(self) -> None:
        summary = build_environment_comparison_summary(_load_input())
        comparison = summary["comparison_sets"][0]
        findings = {
            (item["fact_type"], item["fact_id"]): item
            for item in summary["environment_fact_findings"]
        }

        self.assertEqual(comparison["compared_fact_count"], 9)
        self.assertEqual(
            comparison["finding_counts"],
            {
                "changed": 1,
                "missing": 2,
                "same_declared": 4,
                "unsupported": 1,
                "unverified": 1,
            },
        )
        self.assertEqual(
            findings[("modern_python_environment", "lockfile_path")]["does_not_claim"],
            "dependency_resolution_or_runtime_effect",
        )
        self.assertEqual(
            findings[("external_runtime_note", "external-vna-driver")]["does_not_claim"],
            "fact_truth_or_runtime_availability",
        )
        self.assertEqual(summary["environment_records"][0]["readiness_claim"], "not_checked")
        self.assertEqual(summary["environment_records"][0]["hardware_claim"], "not_probed")

    def test_attention_records_all_boundary_deferrals(self) -> None:
        summary = build_environment_comparison_summary(_load_input())
        source = _load_input()

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            source["attention_expected"],
        )

    def test_boundary_output_keeps_resolution_sync_and_runtime_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-environment-comparison-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "not a package resolver",
            expected["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(
            candidate["environment_comparison_policy"]["dependency_resolution"],
            "not_performed",
        )
        self.assertEqual(
            attention["hardware_probe_not_performed"]["does_not_claim"],
            "control_pc_or_hardware_ready",
        )
        self.assertIn("does not read", expected["boundary_notes"][0])
        self.assertIn("runtime probing", expected["decisions_not_earned"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_comparison_policy"]["dependency_resolution"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "dependency_resolution"):
            build_environment_comparison_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_comparison_policy"]["managed_runner"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_environment_comparison_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_environment_comparison_summary(source)

        source["environment_comparison_policy"]["dependency_sync"] = "mutated"
        source["environment_records"][0]["scope"]["managed_code_version_id"] = "mutated"
        source["environment_records"][0]["declared_environment_facts"][0]["value"] = "mutated"

        self.assertEqual(
            summary["environment_comparison_policy"]["dependency_sync"],
            "not_performed",
        )
        self.assertEqual(
            summary["environment_records"][0]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-reference",
        )
        self.assertEqual(summary["environment_facts"][0]["value"], "uv")

    def test_duplicate_environment_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["environment_records"][0])
        source["environment_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate environment_id"):
            build_environment_comparison_summary(source)

    def test_duplicate_fact_identity_is_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["environment_records"][0]["declared_environment_facts"][0])
        source["environment_records"][0]["declared_environment_facts"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate declared environment fact"):
            build_environment_comparison_summary(source)

    def test_comparison_must_reference_known_environments(self) -> None:
        source = _load_input()
        source["comparison_sets"][0]["comparison_environment_id"] = "missing-environment"

        with self.assertRaisesRegex(ValueError, "missing comparison environment"):
            build_environment_comparison_summary(source)

    def test_comparison_must_use_distinct_environments(self) -> None:
        source = _load_input()
        source["comparison_sets"][0]["comparison_environment_id"] = source["comparison_sets"][0][
            "baseline_environment_id"
        ]

        with self.assertRaisesRegex(ValueError, "distinct declared environments"):
            build_environment_comparison_summary(source)

    def test_claim_shape_must_stay_non_operational(self) -> None:
        source = _load_input()
        source["environment_records"][0]["environment_claims"]["readiness_claim"] = "ready"

        with self.assertRaisesRegex(ValueError, "readiness_claim"):
            build_environment_comparison_summary(source)

    def test_extra_scope_fields_are_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["scope"]["control_pc_ready"] = True

        with self.assertRaisesRegex(ValueError, "scope must match expected shape"):
            build_environment_comparison_summary(source)

    def test_path_facts_must_be_relative(self) -> None:
        source = _load_input()
        source["environment_records"][0]["declared_environment_facts"][1]["value"] = (
            "/private/pyproject.toml"
        )

        with self.assertRaisesRegex(ValueError, "path fact pyproject_path must be relative"):
            build_environment_comparison_summary(source)

    def test_backslash_path_facts_are_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["declared_environment_facts"][2]["value"] = "env\\uv.lock"

        with self.assertRaisesRegex(ValueError, "path fact lockfile_path must be relative"):
            build_environment_comparison_summary(source)

    def test_redacted_fact_values_are_not_emitted(self) -> None:
        source = _load_input()
        for environment in source["environment_records"]:
            fact = environment["declared_environment_facts"][0]
            fact["declaration_state"] = "redacted"
            fact["review_reason"] = "Manager value is intentionally hidden."
            fact["value"] = "SECRET_VALUE"
            environment["record_status"] = "declared_with_review_findings"

        summary = build_environment_comparison_summary(source)
        manager_facts = [
            fact
            for fact in summary["environment_facts"]
            if (fact["fact_type"], fact["fact_id"]) == ("modern_python_environment", "manager")
        ]
        manager_finding = [
            finding
            for finding in summary["environment_fact_findings"]
            if (finding["fact_type"], finding["fact_id"])
            == ("modern_python_environment", "manager")
        ][0]

        self.assertEqual([fact["value"] for fact in manager_facts], [None, None])
        self.assertEqual(manager_finding["finding"], "redacted")
        self.assertIsNone(manager_finding["baseline_value"])
        self.assertIsNone(manager_finding["comparison_value"])

    def test_review_state_requires_reason(self) -> None:
        source = _load_input()
        source["environment_records"][0]["declared_environment_facts"][-1].pop("review_reason")

        with self.assertRaisesRegex(ValueError, "requires review_reason"):
            build_environment_comparison_summary(source)

    def test_declared_state_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["environment_records"][0]["declared_environment_facts"][0]["review_reason"] = (
            "No reason should be attached."
        )

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_environment_comparison_summary(source)

    def test_unsupported_declaration_state_is_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["declared_environment_facts"][0]["declaration_state"] = (
            "ready"
        )

        with self.assertRaisesRegex(ValueError, "unsupported state"):
            build_environment_comparison_summary(source)

    def test_record_status_must_reflect_review_findings(self) -> None:
        source = _load_input()
        source["environment_records"][0]["record_status"] = "declared"

        with self.assertRaisesRegex(ValueError, "declared_with_review_findings"):
            build_environment_comparison_summary(source)


if __name__ == "__main__":
    unittest.main()
