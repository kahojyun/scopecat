from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.environment_readiness import (
    build_environment_readiness_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "environment_readiness" / "basic_plan"


def _load_input() -> dict:
    return json.loads((FIXTURE / "environment-readiness-input.json").read_text(encoding="utf-8"))


class EnvironmentReadinessSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_environment_readiness_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-environment-readiness-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_readiness_plan_prioritizes_modern_uv_manifest(self) -> None:
        summary = build_environment_readiness_summary(_load_input())
        environment = summary["declared_environment_records"][0]
        plan = summary["readiness_plans"][0]

        self.assertEqual(environment["manager"], "uv")
        self.assertEqual(environment["pyproject_path"], "pyproject.toml")
        self.assertEqual(environment["lockfile_path"], "uv.lock")
        self.assertEqual(environment["dependency_groups"], ["default", "lab", "analysis"])
        self.assertEqual(plan["check_count"], 5)
        self.assertEqual(
            plan["check_state_counts"],
            {
                "planned": 3,
                "review_required": 2,
            },
        )
        self.assertEqual(plan["readiness_claim"], "not_checked")
        self.assertEqual(plan["sync_claim"], "not_performed")
        self.assertEqual(plan["execution_claim"], "not_imported_loaded_or_executed")
        self.assertEqual(plan["hardware_claim"], "not_probed")

    def test_external_and_migration_notes_are_review_facts_not_supported_sources(self) -> None:
        summary = build_environment_readiness_summary(_load_input())
        findings = {item["check_id"]: item for item in summary["readiness_findings"]}

        self.assertEqual(
            findings["check-external-vna-driver"]["does_not_claim"],
            "external_tool_available_or_compatible",
        )
        self.assertEqual(
            findings["check-legacy-qcodes-pin"]["does_not_claim"],
            "legacy_environment_migrated",
        )
        self.assertNotIn("dependency_sources", summary["declared_environment_records"][0])
        self.assertNotIn("package_declarations", summary["declared_environment_records"][0])
        self.assertNotIn("external_tools", summary["declared_environment_records"][0])

    def test_boundary_output_keeps_sync_execution_and_hardware_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-environment-readiness-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "not an environment manager", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(
            candidate["environment_readiness_policy"]["dependency_sync"],
            "not_performed",
        )
        self.assertEqual(
            attention["hardware_probe_not_performed"]["does_not_claim"],
            "control_pc_or_hardware_ready",
        )
        self.assertIn("modern uv/pyproject path", expected["boundary_notes"][0])
        self.assertIn("managed runner", expected["decisions_not_earned"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_readiness_policy"]["dependency_sync"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "dependency_sync"):
            build_environment_readiness_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_readiness_policy"]["managed_runner"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_environment_readiness_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_environment_readiness_summary(source)

        source["environment_readiness_policy"]["readiness_claim"] = "mutated"
        source["declared_environment_records"][0]["scope"]["managed_code_version_id"] = "mutated"
        source["declared_environment_records"][0]["modern_python_environment"][
            "dependency_groups"
        ].append("mutated")

        self.assertEqual(
            summary["environment_readiness_policy"]["readiness_claim"],
            "not_claimed",
        )
        self.assertEqual(
            summary["declared_environment_records"][0]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-0001",
        )
        self.assertEqual(
            summary["declared_environment_records"][0]["dependency_groups"],
            ["default", "lab", "analysis"],
        )

    def test_extra_scope_fields_are_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["scope"]["control_pc_ready"] = True
        source["readiness_plans"][0]["scope"]["control_pc_ready"] = True

        with self.assertRaisesRegex(ValueError, "scope must match expected shape"):
            build_environment_readiness_summary(source)

    def test_duplicate_readiness_plan_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["readiness_plans"][0])
        source["readiness_plans"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate readiness_plan_id"):
            build_environment_readiness_summary(source)

    def test_duplicate_check_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["readiness_plans"][0]["check_intentions"][0])
        source["readiness_plans"][0]["check_intentions"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate check_id"):
            build_environment_readiness_summary(source)

    def test_positive_environment_record_status_is_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["record_status"] = "ready_and_synced"

        with self.assertRaisesRegex(ValueError, "record_status"):
            build_environment_readiness_summary(source)

    def test_environment_record_status_must_reflect_review_notes(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["record_status"] = "declared"

        with self.assertRaisesRegex(ValueError, "declared_with_review_findings"):
            build_environment_readiness_summary(source)

    def test_manifest_state_must_stay_declared_in_this_slice(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"]["manifest_state"] = (
            "missing_lockfile"
        )

        with self.assertRaisesRegex(ValueError, "unsupported manifest_state"):
            build_environment_readiness_summary(source)

    def test_unsupported_environment_manager_is_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"]["manager"] = "conda"

        with self.assertRaisesRegex(ValueError, "supports uv"):
            build_environment_readiness_summary(source)

    def test_modern_manifest_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"]["lockfile_path"] = (
            "/private/uv.lock"
        )

        with self.assertRaisesRegex(ValueError, "lockfile_path must be relative"):
            build_environment_readiness_summary(source)

    def test_dependency_groups_are_required(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"][
            "dependency_groups"
        ] = []

        with self.assertRaisesRegex(ValueError, "requires at least one dependency group"):
            build_environment_readiness_summary(source)

    def test_dependency_groups_must_be_non_empty_unique_strings(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"][
            "dependency_groups"
        ] = ["default", "", "default"]

        with self.assertRaisesRegex(ValueError, "non-empty strings"):
            build_environment_readiness_summary(source)

    def test_duplicate_dependency_groups_are_rejected(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["modern_python_environment"][
            "dependency_groups"
        ] = ["default", "lab", "lab"]

        with self.assertRaisesRegex(ValueError, "duplicate dependency group"):
            build_environment_readiness_summary(source)

    def test_duplicate_external_runtime_notes_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(
            source["declared_environment_records"][0]["external_runtime_notes"][0]
        )
        source["declared_environment_records"][0]["external_runtime_notes"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate note_id"):
            build_environment_readiness_summary(source)

    def test_review_notes_require_review_reason(self) -> None:
        source = _load_input()
        source["declared_environment_records"][0]["external_runtime_notes"][0].pop("review_reason")

        with self.assertRaisesRegex(ValueError, "requires review_reason"):
            build_environment_readiness_summary(source)

    def test_readiness_plan_must_reference_known_declared_environment(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["declared_environment_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing declared environment"):
            build_environment_readiness_summary(source)

    def test_readiness_plan_scope_must_match_declared_environment(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["scope"]["managed_code_version_id"] = (
            "managed-code-version-other"
        )

        with self.assertRaisesRegex(ValueError, "scope must match"):
            build_environment_readiness_summary(source)

    def test_readiness_plan_status_must_reflect_review_checks(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["record_status"] = "planned"

        with self.assertRaisesRegex(ValueError, "planned_with_review_findings"):
            build_environment_readiness_summary(source)

    def test_extra_readiness_claim_fields_are_rejected(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["readiness_claims"]["runtime_ready"] = True

        with self.assertRaisesRegex(ValueError, "claims must match expected shape"):
            build_environment_readiness_summary(source)

    def test_check_type_must_be_known(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][0]["check_type"] = (
            "dependency_sync_performed"
        )

        with self.assertRaisesRegex(ValueError, "unsupported check_type"):
            build_environment_readiness_summary(source)

    def test_check_subject_type_must_match_check_type(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][0]["subject_type"] = "migration_note"

        with self.assertRaisesRegex(ValueError, "subject_type must be"):
            build_environment_readiness_summary(source)

    def test_check_subject_must_exist_in_declared_environment(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][0]["subject_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing subject"):
            build_environment_readiness_summary(source)

    def test_planned_check_must_not_carry_review_reason(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][0]["review_reason"] = "already ran"

        with self.assertRaisesRegex(ValueError, "planned check must not carry reason"):
            build_environment_readiness_summary(source)

    def test_review_check_requires_review_reason(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][3].pop("review_reason")

        with self.assertRaisesRegex(ValueError, "requires review_reason"):
            build_environment_readiness_summary(source)

    def test_review_notes_require_matching_review_checks(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"].pop(3)

        with self.assertRaisesRegex(ValueError, "requires matching review check"):
            build_environment_readiness_summary(source)

    def test_review_note_check_state_must_match_note_state(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][3]["state"] = "blocked"
        source["readiness_plans"][0]["check_intentions"][3]["review_reason"] = (
            "External driver blocks environment review."
        )

        with self.assertRaisesRegex(ValueError, "requires matching review check"):
            build_environment_readiness_summary(source)

    def test_does_not_claim_is_derived_not_fixture_supplied(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["check_intentions"][0]["does_not_claim"] = "run_can_start"

        summary = build_environment_readiness_summary(source)

        self.assertEqual(
            summary["planned_checks"][0]["does_not_claim"],
            "environment_files_observed_or_verified",
        )

    def test_positive_readiness_claims_are_rejected(self) -> None:
        source = _load_input()
        source["readiness_plans"][0]["readiness_claims"]["readiness_claim"] = "ready"

        with self.assertRaisesRegex(ValueError, "readiness_claim"):
            build_environment_readiness_summary(source)


if __name__ == "__main__":
    unittest.main()
