from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.declared_environment_inventory import (
    build_declared_environment_inventory_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "declared_environment_inventory" / "basic_inventory"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "declared-environment-inventory-input.json").read_text(encoding="utf-8")
    )


class DeclaredEnvironmentInventorySummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_declared_environment_inventory_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-declared-environment-inventory-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_environment_record_summarizes_declared_inventory_without_sync(self) -> None:
        summary = build_declared_environment_inventory_summary(_load_input())
        environment = summary["environment_records"][0]

        self.assertEqual(
            environment["environment_id"],
            "declared-environment-chevron-qA-0001",
        )
        self.assertEqual(environment["dependency_source_count"], 3)
        self.assertEqual(environment["package_declaration_count"], 3)
        self.assertEqual(environment["package_pin_counts"]["unpinned"], 1)
        self.assertEqual(environment["external_tool_state_counts"]["unverified"], 1)
        self.assertEqual(environment["readiness_claim"], "not_checked")
        self.assertEqual(environment["sync_claim"], "not_synced")
        self.assertEqual(
            environment["execution_claim"],
            "not_imported_loaded_or_executed",
        )

    def test_environment_findings_are_not_readiness_claims(self) -> None:
        summary = build_declared_environment_inventory_summary(_load_input())
        findings = {item["finding"]: item for item in summary["environment_findings"]}

        self.assertEqual(
            findings["dependency_source_unavailable"]["does_not_claim"],
            "environment_is_unusable_or_runnable",
        )
        self.assertEqual(
            findings["package_pin_unpinned"]["does_not_claim"],
            "dependency_resolution_or_runtime_readiness",
        )
        self.assertEqual(
            findings["external_tool_unverified"]["does_not_claim"],
            "external_tool_available_or_compatible",
        )

    def test_boundary_output_keeps_runtime_and_execution_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-declared-environment-inventory-summary.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not a package resolver", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["declared_environment_inventory_policy"]["dependency_sync"],
            "not_performed",
        )
        self.assertEqual(
            attention["environment_readiness_not_claimed"]["does_not_claim"],
            "run_can_start",
        )
        self.assertIn("Package pins", expected["boundary_notes"][1])
        self.assertIn("code execution", expected["decisions_not_earned"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_inventory_policy"]["dependency_sync"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "dependency_sync"):
            build_declared_environment_inventory_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_inventory_policy"]["package_resolution"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_declared_environment_inventory_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_declared_environment_inventory_summary(source)

        source["declared_environment_inventory_policy"]["dependency_sync"] = "mutated"
        source["environment_records"][0]["scope"]["managed_code_version_id"] = "mutated"
        source["environment_records"][0]["dependency_sources"][0]["path"] = "mutated"

        self.assertEqual(
            summary["declared_environment_inventory_policy"]["dependency_sync"],
            "not_performed",
        )
        self.assertEqual(
            summary["environment_records"][0]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-0001",
        )
        self.assertEqual(summary["dependency_sources"][0]["path"], "pyproject.toml")

    def test_duplicate_environment_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["environment_records"][0])
        source["environment_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate environment_id"):
            build_declared_environment_inventory_summary(source)

    def test_duplicate_dependency_source_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["environment_records"][0]["dependency_sources"][0])
        source["environment_records"][0]["dependency_sources"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate source_id"):
            build_declared_environment_inventory_summary(source)

    def test_dependency_source_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["path"] = "/private/uv.lock"

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_declared_environment_inventory_summary(source)

    def test_backslash_dependency_source_paths_are_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["path"] = "env\\uv.lock"

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_declared_environment_inventory_summary(source)

    def test_blank_dependency_source_paths_are_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["path"] = ""

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_declared_environment_inventory_summary(source)

    def test_current_directory_dependency_source_paths_are_rejected(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["path"] = "."

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_declared_environment_inventory_summary(source)

    def test_dependency_source_lockfile_ref_must_be_known(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["lockfile_ref"] = "missing"

        with self.assertRaisesRegex(ValueError, "lockfile_ref"):
            build_declared_environment_inventory_summary(source)

    def test_runtime_hint_source_ref_must_be_known(self) -> None:
        source = _load_input()
        source["environment_records"][0]["runtime_hints"][0]["source_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "runtime hint"):
            build_declared_environment_inventory_summary(source)

    def test_runtime_hint_findings_are_reported(self) -> None:
        source = _load_input()
        source["environment_records"][0]["runtime_hints"][0]["declaration_state"] = "unsupported"
        source["environment_records"][0]["runtime_hints"][0]["missing_reason"] = (
            "Interpreter constraint uses a project-specific selector."
        )

        summary = build_declared_environment_inventory_summary(source)

        self.assertIn(
            {
                "environment_id": "declared-environment-chevron-qA-0001",
                "subject_type": "runtime_hint",
                "subject_id": "Python runtime",
                "severity": "review",
                "finding": "runtime_hint_unsupported",
                "basis": "Interpreter constraint uses a project-specific selector.",
                "does_not_claim": "runtime_available_or_compatible",
            },
            summary["environment_findings"],
        )

    def test_package_source_ref_must_be_known(self) -> None:
        source = _load_input()
        source["environment_records"][0]["package_declarations"][0]["source_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing dependency source"):
            build_declared_environment_inventory_summary(source)

    def test_declared_package_requires_source_ref(self) -> None:
        source = _load_input()
        source["environment_records"][0]["package_declarations"][0]["source_id"] = None

        with self.assertRaisesRegex(ValueError, "requires source_id"):
            build_declared_environment_inventory_summary(source)

    def test_unavailable_source_needs_reason(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][2].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "requires missing_reason"):
            build_declared_environment_inventory_summary(source)

    def test_declared_source_must_not_carry_missing_reason(self) -> None:
        source = _load_input()
        source["environment_records"][0]["dependency_sources"][0]["missing_reason"] = (
            "should not be here"
        )

        with self.assertRaisesRegex(ValueError, "must not carry missing_reason"):
            build_declared_environment_inventory_summary(source)

    def test_duplicate_package_role_is_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["environment_records"][0]["package_declarations"][0])
        source["environment_records"][0]["package_declarations"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate package role"):
            build_declared_environment_inventory_summary(source)

    def test_environment_claims_must_stay_non_readiness_claims(self) -> None:
        source = _load_input()
        source["environment_records"][0]["environment_claims"]["readiness_claim"] = "ready"

        with self.assertRaisesRegex(ValueError, "readiness claim"):
            build_declared_environment_inventory_summary(source)

    def test_environment_authority_must_stay_declared_only(self) -> None:
        source = _load_input()
        source["environment_records"][0]["authority"] = "observed_runtime_inventory"

        with self.assertRaisesRegex(ValueError, "authority"):
            build_declared_environment_inventory_summary(source)

    def test_environment_record_status_must_not_claim_readiness(self) -> None:
        source = _load_input()
        source["environment_records"][0]["record_status"] = "ready_and_synced"

        with self.assertRaisesRegex(ValueError, "record_status"):
            build_declared_environment_inventory_summary(source)


if __name__ == "__main__":
    unittest.main()
