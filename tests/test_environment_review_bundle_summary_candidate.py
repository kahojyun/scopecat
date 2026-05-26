from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.environment_review_bundle import (
    build_environment_review_bundle_summary,
)
from implementation_candidates.environment_review_bundle.contracts import (
    COMPARISON_FINDING_STATES,
    COMPARISON_FINDINGS_IGNORED_FOR_REVIEW,
    COMPARISON_FINDINGS_REQUIRING_REVIEW,
    COMPARISON_STATE_COUNTS,
    EXPECTED_POLICY,
    FILE_FINDING_DOES_NOT_CLAIM,
    FILE_OBSERVATION_CLASSIFICATION_FINDINGS,
    FILE_OBSERVATION_CLASSIFICATIONS,
    FILE_OBSERVATION_FINDINGS,
    OBSERVATION_STATUS_COUNTS,
    POLICY_ATTENTION_MATRIX,
    READINESS_CHECK_STATE_COUNTS,
    READINESS_FINDING_DOES_NOT_CLAIM,
    READINESS_FINDING_STATES,
    READINESS_FINDINGS,
    validate_environment_review_bundle_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "environment_review_bundle" / "basic_bundle"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "environment-review-bundle-input.json").read_text(encoding="utf-8")
    )


class EnvironmentReviewBundleSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_environment_review_bundle_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-environment-review-bundle-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_bundle_aggregates_prior_findings_without_claiming_readiness(self) -> None:
        summary = build_environment_review_bundle_summary(_load_input())
        bundle = summary["review_bundles"][0]
        source_counts = summary["finding_source_counts"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            bundle["classification"],
            "environment_review_has_planned_check_findings",
        )
        self.assertEqual(
            bundle["comparison_review_finding_counts"]["declared_environment_fact_changed"], 1
        )
        self.assertEqual(source_counts["environment_comparison"], 4)
        self.assertEqual(source_counts["environment_file_observation"], 0)
        self.assertEqual(source_counts["environment_readiness_plan"], 2)
        self.assertEqual(
            attention["runnable_readiness_not_claimed"]["does_not_claim"],
            "run_can_start",
        )

    def test_policy_attention_matrix_covers_explicit_policy_boundaries(self) -> None:
        expected_policy_keys = {
            "summary_policy",
            "dependency_resolution",
            "dependency_sync",
            "package_install",
            "runtime_probe",
            "code_import_execution",
            "hardware_probe",
            "managed_runner",
            "readiness_claim",
            "shared_environment_schema",
        }
        matrix_policy_keys = {row["policy_key"] for row in POLICY_ATTENTION_MATRIX}
        matrix_codes = [row["code"] for row in POLICY_ATTENTION_MATRIX]

        self.assertEqual(matrix_policy_keys, expected_policy_keys)
        self.assertEqual(len(matrix_codes), len(set(matrix_codes)))
        for row in POLICY_ATTENTION_MATRIX:
            with self.subTest(policy_key=row["policy_key"]):
                self.assertEqual(EXPECTED_POLICY[row["policy_key"]], row["policy_value"])
                self.assertIn(row["severity"], {"info", "review"})
                self.assertTrue(row["basis"])
                self.assertTrue(row["does_not_claim"])

    def test_contract_matrices_cover_finding_and_count_vocabularies(self) -> None:
        comparison_findings = (
            COMPARISON_FINDINGS_REQUIRING_REVIEW | COMPARISON_FINDINGS_IGNORED_FOR_REVIEW
        )
        self.assertEqual(set(COMPARISON_FINDING_STATES), comparison_findings)
        self.assertEqual(set(COMPARISON_FINDING_STATES.values()), COMPARISON_STATE_COUNTS)
        self.assertEqual(set(READINESS_FINDING_STATES), READINESS_FINDINGS)
        self.assertLessEqual(set(READINESS_FINDING_STATES.values()), READINESS_CHECK_STATE_COUNTS)
        self.assertIn(
            "planned", READINESS_CHECK_STATE_COUNTS - set(READINESS_FINDING_STATES.values())
        )
        self.assertEqual(
            set(FILE_OBSERVATION_CLASSIFICATION_FINDINGS), FILE_OBSERVATION_CLASSIFICATIONS
        )
        self.assertEqual(
            set().union(*FILE_OBSERVATION_CLASSIFICATION_FINDINGS.values()),
            FILE_OBSERVATION_FINDINGS,
        )
        self.assertEqual(set(FILE_FINDING_DOES_NOT_CLAIM), FILE_OBSERVATION_FINDINGS)
        self.assertEqual(set(READINESS_FINDING_DOES_NOT_CLAIM), READINESS_FINDINGS)
        self.assertEqual(OBSERVATION_STATUS_COUNTS, {"observed", "unavailable"})

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_review_bundle_policy"]["dependency_sync"] = "performed"

        with self.assertRaisesRegex(ValueError, "dependency_sync"):
            build_environment_review_bundle_summary(source)

    def test_summary_policy_must_be_review_summary(self) -> None:
        source = _load_input()
        source["environment_review_bundle_policy"]["summary_policy"] = "export/package"

        with self.assertRaisesRegex(ValueError, "summary_policy"):
            build_environment_review_bundle_summary(source)

    def test_extra_policy_keys_are_rejected(self) -> None:
        source = _load_input()
        source["environment_review_bundle_policy"]["managed_runner_operation"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_environment_review_bundle_summary(source)

    def test_extra_top_level_keys_are_rejected(self) -> None:
        source = _load_input()
        source["package_install_results"] = []

        with self.assertRaisesRegex(ValueError, "environment review bundle source"):
            build_environment_review_bundle_summary(source)

    def test_missing_top_level_keys_are_rejected(self) -> None:
        source = _load_input()
        del source["comparison_findings"]

        with self.assertRaisesRegex(ValueError, "environment review bundle source"):
            build_environment_review_bundle_summary(source)

    def test_top_level_record_collections_must_be_lists(self) -> None:
        cases = [
            ("environment_contexts", "environment_id records must be a list", {}),
            ("comparison_findings", "comparison_findings must be a list", {}),
            ("file_observation_findings", "file_observation_findings must be a list", {}),
            ("readiness_findings", "readiness_findings must be a list", {}),
        ]
        for collection_key, message, invalid_value in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key] = invalid_value

                with self.assertRaisesRegex(ValueError, message):
                    build_environment_review_bundle_summary(source)

    def test_selected_record_extra_fields_are_rejected(self) -> None:
        cases = [
            ("prepared_run_contexts", "runtime_probe_result"),
            ("rerun_preparations", "dependency_sync"),
            ("environment_contexts", "run_blocking_decision"),
            ("environment_comparisons", "runtime_compatibility"),
            ("environment_file_observations", "dependency_resolution"),
            ("review_bundles", "managed_runner"),
        ]
        for collection_key, extra_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][extra_key] = "claimed"

                with self.assertRaisesRegex(ValueError, "expected shape"):
                    build_environment_review_bundle_summary(source)

    def test_record_collection_items_must_be_mappings(self) -> None:
        cases = [
            "prepared_run_contexts",
            "environment_file_observations",
        ]
        for collection_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0] = "not-a-record"

                with self.assertRaisesRegex(ValueError, "record must be a mapping"):
                    build_environment_review_bundle_summary(source)

    def test_finding_collection_items_must_be_mappings(self) -> None:
        cases = [
            "comparison_findings",
            "file_observation_findings",
            "readiness_findings",
        ]
        for collection_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                if not source[collection_key]:
                    source[collection_key].append("not-a-finding")
                else:
                    source[collection_key][0] = "not-a-finding"

                with self.assertRaisesRegex(ValueError, "must match expected shape"):
                    build_environment_review_bundle_summary(source)

    def test_finding_row_extra_fields_are_rejected(self) -> None:
        cases = [
            ("comparison_findings", "run_blocking_decision"),
            ("file_observation_findings", "dependency_sync"),
            ("readiness_findings", "package_install_result"),
        ]
        for collection_key, extra_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                if not source[collection_key]:
                    source[collection_key].append(
                        {
                            "bundle_id": "environment-review-bundle-chevron-qA-0001",
                            "file_observation_id": "environment-file-observation-chevron-qA-current",
                            "finding": "environment_file_digest_mismatch",
                            "basis": "Observed sha256 digest differs from the declared environment file digest.",
                            "does_not_claim": "dependency_resolution_or_file_repair",
                        }
                    )
                source[collection_key][0][extra_key] = "claimed"

                with self.assertRaisesRegex(ValueError, "expected shape"):
                    build_environment_review_bundle_summary(source)

    def test_positive_bundle_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_bundles"][0]["bundle_claim"] = "ready_to_run"

        with self.assertRaisesRegex(ValueError, "environment review bundle claim"):
            build_environment_review_bundle_summary(source)

    def test_selected_claim_fields_are_rejected(self) -> None:
        cases = [
            (
                "prepared_run_contexts",
                "preparation_claim",
                "ready_to_run",
                "prepared run context claim",
            ),
            (
                "rerun_preparations",
                "preparation_claim",
                "automatic_rerun",
                "rerun preparation claim",
            ),
            (
                "environment_comparisons",
                "comparison_claim",
                "runtime_compatible",
                "comparison claim",
            ),
            (
                "environment_file_observations",
                "classification",
                "dependency_sync_performed",
                "classification",
            ),
        ]
        for collection_key, field, value, message in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_environment_review_bundle_summary(source)

    def test_selected_enum_fields_must_be_strings(self) -> None:
        cases = [
            ("environment_contexts", "role"),
            ("environment_contexts", "record_status"),
            ("environment_file_observations", "classification"),
        ]
        for collection_key, field in cases:
            with self.subTest(collection_key=collection_key, field=field):
                source = _load_input()
                source[collection_key][0][field] = []

                with self.assertRaisesRegex(ValueError, "non-empty string"):
                    build_environment_review_bundle_summary(source)

    def test_bundle_selected_reference_must_match_rerun_preparation(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["selected_reference_id"] = "other-reference"

        with self.assertRaisesRegex(ValueError, "selected reference"):
            build_environment_review_bundle_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_environment_review_bundle_summary(source)

        source["environment_review_bundle_policy"]["runtime_probe"] = "mutated"
        source["prepared_run_contexts"][0]["scope"]["managed_code_version_id"] = "mutated"
        source["environment_contexts"][0]["environment_claims"]["readiness_claim"] = "mutated"

        self.assertEqual(
            summary["environment_review_bundle_policy"]["runtime_probe"],
            "not_performed",
        )
        self.assertEqual(
            summary["prepared_run_contexts"][0]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-current",
        )
        self.assertEqual(
            summary["environment_contexts"][0]["environment_claims"]["readiness_claim"],
            "not_checked",
        )

    def test_unbundled_top_level_records_are_not_projected(self) -> None:
        source = _load_input()
        extra_context = copy.deepcopy(source["prepared_run_contexts"][0])
        extra_context["prepared_run_context_id"] = "prepared-run-context-unused"
        extra_context["scope"]["prepared_run_context_id"] = "prepared-run-context-unused"
        source["prepared_run_contexts"].append(extra_context)

        summary = build_environment_review_bundle_summary(source)

        self.assertEqual(
            [item["prepared_run_context_id"] for item in summary["prepared_run_contexts"]],
            ["prepared-run-context-chevron-qA-current"],
        )

    def test_unbundled_non_context_top_level_records_are_not_projected(self) -> None:
        cases = [
            ("rerun_preparations", "rerun_preparation_id"),
            ("environment_contexts", "environment_id"),
            ("environment_comparisons", "comparison_id"),
            ("environment_file_observations", "file_observation_id"),
            ("environment_readiness_plans", "readiness_plan_id"),
        ]
        for collection_key, id_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                extra_record = copy.deepcopy(source[collection_key][-1])
                extra_record[id_key] = f"{extra_record[id_key]}-unused"
                source[collection_key].append(extra_record)

                summary = build_environment_review_bundle_summary(source)

                projected_ids = {item[id_key] for item in summary[collection_key]}
                self.assertNotIn(extra_record[id_key], projected_ids)

    def test_invalid_unbundled_top_level_records_are_not_validated(self) -> None:
        cases = [
            ("prepared_run_contexts", "prepared_run_context_id", "selected_context_count"),
            ("rerun_preparations", "rerun_preparation_id", "preparation_claim"),
            ("environment_contexts", "environment_id", "environment_claims"),
            ("environment_comparisons", "comparison_id", "finding_state_counts"),
            ("environment_file_observations", "file_observation_id", "observation_status_counts"),
            ("environment_readiness_plans", "readiness_plan_id", "check_state_counts"),
        ]
        for collection_key, id_key, invalid_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                extra_record = copy.deepcopy(source[collection_key][-1])
                extra_record[id_key] = f"{extra_record[id_key]}-unused"
                extra_record["runtime_probe_result"] = "claimed"
                extra_record[invalid_key] = {"invalid_state": True}
                source[collection_key].append(extra_record)

                summary = build_environment_review_bundle_summary(source)

                projected_ids = {item[id_key] for item in summary[collection_key]}
                self.assertNotIn(extra_record[id_key], projected_ids)

    def test_unbundled_records_still_need_indexable_ids(self) -> None:
        source = _load_input()
        extra_context = copy.deepcopy(source["prepared_run_contexts"][0])
        del extra_context["prepared_run_context_id"]
        source["prepared_run_contexts"].append(extra_context)

        with self.assertRaisesRegex(ValueError, "must match expected shape"):
            build_environment_review_bundle_summary(source)

    def test_duplicate_bundle_ids_are_rejected(self) -> None:
        source = _load_input()
        source["review_bundles"].append(copy.deepcopy(source["review_bundles"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate bundle_id"):
            build_environment_review_bundle_summary(source)

    def test_duplicate_unbundled_record_ids_are_rejected(self) -> None:
        source = _load_input()
        extra_context = copy.deepcopy(source["prepared_run_contexts"][0])
        extra_context["runtime_probe_result"] = "claimed"
        source["prepared_run_contexts"].append(extra_context)

        with self.assertRaisesRegex(ValueError, "duplicate prepared_run_context_id"):
            build_environment_review_bundle_summary(source)

    def test_bundle_must_reference_known_prepared_context(self) -> None:
        source = _load_input()
        source["review_bundles"][0]["prepared_run_context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing prepared run context"):
            build_environment_review_bundle_summary(source)

    def test_bundle_must_reference_known_component_records(self) -> None:
        cases = [
            ("rerun_preparation_id", "missing rerun preparation"),
            ("reference_environment_id", "missing reference environment"),
            ("current_environment_id", "missing current environment"),
            ("environment_comparison_id", "missing environment comparison"),
            ("environment_file_observation_id", "missing file observation"),
            ("environment_readiness_plan_id", "missing readiness plan"),
        ]
        for bundle_key, message in cases:
            with self.subTest(bundle_key=bundle_key):
                source = _load_input()
                source["review_bundles"][0][bundle_key] = "missing"

                with self.assertRaisesRegex(ValueError, message):
                    build_environment_review_bundle_summary(source)

    def test_rerun_must_point_at_bundled_prepared_context(self) -> None:
        source = _load_input()
        source["rerun_preparations"][0]["prepared_run_context_id"] = "other-context"

        with self.assertRaisesRegex(ValueError, "bundled prepared run context"):
            build_environment_review_bundle_summary(source)

    def test_prepared_context_scope_must_reference_itself(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["scope"]["prepared_run_context_id"] = "other-context"

        with self.assertRaisesRegex(ValueError, "scope must reference itself"):
            build_environment_review_bundle_summary(source)

    def test_current_environment_scope_must_match_prepared_context(self) -> None:
        source = _load_input()
        source["environment_contexts"][1]["scope"]["editable_workspace_id"] = "other-workspace"

        with self.assertRaisesRegex(ValueError, "current environment scope"):
            build_environment_review_bundle_summary(source)

    def test_environment_role_must_match_bundle_role(self) -> None:
        source = _load_input()
        source["environment_contexts"][1]["role"] = "selected_reference_environment"

        with self.assertRaisesRegex(ValueError, "current environment role"):
            build_environment_review_bundle_summary(source)

    def test_reference_environment_role_must_match_bundle_role(self) -> None:
        source = _load_input()
        source["environment_contexts"][0]["role"] = "current_environment"

        with self.assertRaisesRegex(ValueError, "reference environment role"):
            build_environment_review_bundle_summary(source)

    def test_environment_record_status_must_stay_declaration_only(self) -> None:
        source = _load_input()
        source["environment_contexts"][1]["record_status"] = "runtime_ready"

        with self.assertRaisesRegex(ValueError, "record_status"):
            build_environment_review_bundle_summary(source)

    def test_reference_environment_record_status_must_stay_declaration_only(self) -> None:
        source = _load_input()
        source["environment_contexts"][0]["record_status"] = "runtime_ready"

        with self.assertRaisesRegex(ValueError, "record_status"):
            build_environment_review_bundle_summary(source)

    def test_comparison_must_match_bundled_environment_pair(self) -> None:
        source = _load_input()
        source["environment_comparisons"][0]["comparison_environment_id"] = (
            "declared-environment-chevron-qA-reference"
        )

        with self.assertRaisesRegex(ValueError, "comparison current side"):
            build_environment_review_bundle_summary(source)

    def test_reference_environment_must_match_bundle_managed_code_version(self) -> None:
        source = _load_input()
        source["review_bundles"][0]["reference_managed_code_version_id"] = "other-version"

        with self.assertRaisesRegex(ValueError, "reference managed code version"):
            build_environment_review_bundle_summary(source)

    def test_comparison_baseline_must_match_reference_environment(self) -> None:
        source = _load_input()
        source["environment_comparisons"][0]["baseline_environment_id"] = (
            "declared-environment-chevron-qA-current"
        )

        with self.assertRaisesRegex(ValueError, "comparison baseline"):
            build_environment_review_bundle_summary(source)

    def test_comparison_finding_source_must_match_bundled_comparison(self) -> None:
        source = _load_input()
        source["comparison_findings"][0]["comparison_id"] = "missing-comparison"

        with self.assertRaisesRegex(ValueError, "comparison finding source"):
            build_environment_review_bundle_summary(source)

    def test_finding_rows_must_reference_bundled_review_bundle(self) -> None:
        cases = [
            "comparison_findings",
            "file_observation_findings",
            "readiness_findings",
        ]
        for collection_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                if not source[collection_key]:
                    source[collection_key].append(
                        {
                            "bundle_id": "environment-review-bundle-chevron-qA-0001",
                            "file_observation_id": "environment-file-observation-chevron-qA-current",
                            "finding": "environment_file_digest_mismatch",
                            "basis": "Observed sha256 digest differs from the declared environment file digest.",
                            "does_not_claim": "dependency_resolution_or_file_repair",
                        }
                    )
                    source["environment_file_observations"][0]["classification"] = (
                        "environment_files_observed_with_mismatch"
                    )
                source[collection_key][0]["bundle_id"] = "missing-bundle"

                with self.assertRaisesRegex(ValueError, "must reference bundled review bundle"):
                    build_environment_review_bundle_summary(source)

    def test_comparison_finding_codes_are_bounded(self) -> None:
        source = _load_input()
        source["comparison_findings"][0]["finding"] = "dependency_sync_performed"

        with self.assertRaisesRegex(ValueError, "comparison finding is unsupported"):
            build_environment_review_bundle_summary(source)

    def test_same_comparison_findings_are_not_projected_as_review_findings(self) -> None:
        source = _load_input()
        source["environment_comparisons"][0]["fact_count"] = 1
        source["environment_comparisons"][0]["finding_state_counts"] = {
            "changed": 0,
            "missing": 0,
            "same_declared": 1,
            "unsupported": 0,
            "unverified": 0,
        }
        source["comparison_findings"] = [
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "comparison_id": "environment-comparison-chevron-qA-reference-to-current",
                "finding": "declared_environment_fact_same",
                "basis": "Both sides declare uv as the environment manager.",
            }
        ]

        summary = build_environment_review_bundle_summary(source)

        self.assertEqual(summary["finding_source_counts"]["environment_comparison"], 0)
        self.assertEqual(summary["review_bundles"][0]["comparison_review_finding_counts"], {})

    def test_file_observation_must_reference_current_environment(self) -> None:
        source = _load_input()
        source["environment_file_observations"][0]["environment_id"] = (
            "declared-environment-chevron-qA-reference"
        )

        with self.assertRaisesRegex(ValueError, "file observation"):
            build_environment_review_bundle_summary(source)

    def test_file_observation_finding_source_must_match_bundled_observation(self) -> None:
        source = _load_input()
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "missing-observation",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        with self.assertRaisesRegex(ValueError, "file observation finding source"):
            build_environment_review_bundle_summary(source)

    def test_file_observation_finding_codes_are_bounded(self) -> None:
        source = _load_input()
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "dependency_sync_performed",
                "basis": "Unsupported operational finding.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        with self.assertRaisesRegex(ValueError, "file observation finding is unsupported"):
            build_environment_review_bundle_summary(source)

    def test_file_observation_finding_does_not_claim_is_bounded(self) -> None:
        source = _load_input()
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "run_can_start",
            }
        )

        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            build_environment_review_bundle_summary(source)

    def test_finding_basis_must_be_non_empty_string(self) -> None:
        cases = [
            ("comparison_findings", "basis", 123),
            ("comparison_findings", "finding", []),
            ("file_observation_findings", "basis", ""),
            ("file_observation_findings", "file_observation_id", 123),
            ("file_observation_findings", "finding", []),
            ("file_observation_findings", "does_not_claim", []),
            ("readiness_findings", "bundle_id", ["environment-review-bundle-chevron-qA-0001"]),
            ("readiness_findings", "readiness_plan_id", 123),
            ("readiness_findings", "finding", []),
            ("readiness_findings", "does_not_claim", []),
        ]
        for collection_key, field, invalid_value in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                if not source[collection_key]:
                    source[collection_key].append(
                        {
                            "bundle_id": "environment-review-bundle-chevron-qA-0001",
                            "file_observation_id": "environment-file-observation-chevron-qA-current",
                            "finding": "environment_file_digest_mismatch",
                            "basis": "Observed sha256 digest differs from the declared environment file digest.",
                            "does_not_claim": "dependency_resolution_or_file_repair",
                        }
                    )
                    source["environment_file_observations"][0]["classification"] = (
                        "environment_files_observed_with_mismatch"
                    )
                source[collection_key][0][field] = invalid_value

                with self.assertRaisesRegex(ValueError, "non-empty string"):
                    build_environment_review_bundle_summary(source)

    def test_finding_rows_must_include_required_keys(self) -> None:
        cases = [
            ("comparison_findings", "comparison_id"),
            ("file_observation_findings", "file_observation_id"),
            ("readiness_findings", "bundle_id"),
        ]
        for collection_key, missing_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                if not source[collection_key]:
                    source[collection_key].append(
                        {
                            "bundle_id": "environment-review-bundle-chevron-qA-0001",
                            "file_observation_id": "environment-file-observation-chevron-qA-current",
                            "finding": "environment_file_digest_mismatch",
                            "basis": "Observed sha256 digest differs from the declared environment file digest.",
                            "does_not_claim": "dependency_resolution_or_file_repair",
                        }
                    )
                    source["environment_file_observations"][0]["classification"] = (
                        "environment_files_observed_with_mismatch"
                    )
                del source[collection_key][0][missing_key]

                with self.assertRaisesRegex(ValueError, "expected shape"):
                    build_environment_review_bundle_summary(source)

    def test_file_observation_findings_are_projected_and_prioritized(self) -> None:
        source = _load_input()
        source["environment_file_observations"][0]["classification"] = (
            "environment_files_observed_with_mismatch"
        )
        source["environment_file_observations"][0]["review_finding_count"] = 99
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        summary = build_environment_review_bundle_summary(source)
        bundle = summary["review_bundles"][0]
        file_findings = [
            finding
            for finding in summary["environment_review_findings"]
            if finding["source_kind"] == "environment_file_observation"
        ]

        self.assertEqual(
            bundle["classification"], "environment_review_has_file_observation_findings"
        )
        self.assertEqual(bundle["file_observation_finding_count"], 1)
        self.assertEqual(summary["finding_source_counts"]["environment_file_observation"], 1)
        self.assertEqual(summary["environment_file_observations"][0]["review_finding_count"], 1)
        self.assertEqual(file_findings[0]["severity"], "review")
        self.assertEqual(file_findings[0]["finding"], "environment_file_digest_mismatch")
        self.assertEqual(
            file_findings[0]["basis"],
            "Observed sha256 digest differs from the declared environment file digest.",
        )
        self.assertEqual(
            file_findings[0]["source_id"], "environment-file-observation-chevron-qA-current"
        )
        self.assertEqual(file_findings[0]["does_not_claim"], "dependency_resolution_or_file_repair")

    def test_file_observation_review_finding_count_is_derived_from_projected_findings(self) -> None:
        source = _load_input()
        source["environment_file_observations"][0]["review_finding_count"] = 99

        summary = build_environment_review_bundle_summary(source)

        self.assertEqual(summary["environment_file_observations"][0]["review_finding_count"], 0)

    def test_file_observation_classification_must_not_contradict_projected_findings(self) -> None:
        source = _load_input()
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        with self.assertRaisesRegex(ValueError, "classification"):
            build_environment_review_bundle_summary(source)

    def test_file_observation_review_finding_classification_requires_projected_findings(
        self,
    ) -> None:
        cases = [
            "environment_files_observed_with_review_findings",
            "environment_files_observed_with_mismatch",
            "environment_files_unavailable_for_review",
        ]
        for classification in cases:
            with self.subTest(classification=classification):
                source = _load_input()
                source["environment_file_observations"][0]["classification"] = classification

                with self.assertRaisesRegex(ValueError, "classification"):
                    build_environment_review_bundle_summary(source)

    def test_contract_validation_rejects_file_classification_contradictions(self) -> None:
        source = _load_input()
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0001",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        with self.assertRaisesRegex(ValueError, "classification"):
            validate_environment_review_bundle_contract(source)

    def test_file_observation_finding_family_must_match_classification(self) -> None:
        cases = [
            (
                "environment_files_observed_with_review_findings",
                "environment_file_unavailable",
                {"unavailable": 1},
                "environment_repair_or_dependency_sync",
            ),
            (
                "environment_files_unavailable_for_review",
                "environment_file_digest_mismatch",
                {"observed": 2, "unavailable": 1},
                "dependency_resolution_or_file_repair",
            ),
            (
                "environment_files_observed_with_mismatch",
                "environment_file_unavailable",
                {"observed": 2},
                "environment_repair_or_dependency_sync",
            ),
            (
                "environment_files_observed_with_review_findings",
                "environment_file_digest_mismatch",
                {"observed": 2},
                "dependency_resolution_or_file_repair",
            ),
            (
                "environment_files_observed_with_mismatch",
                "environment_file_parse_failed",
                {"observed": 2},
                "dependency_resolution_or_runtime_compatibility",
            ),
        ]
        for classification, finding, status_counts, does_not_claim in cases:
            with self.subTest(classification=classification, finding=finding):
                source = _load_input()
                source["environment_file_observations"][0]["classification"] = classification
                source["environment_file_observations"][0]["observation_status_counts"] = (
                    status_counts
                )
                source["file_observation_findings"].append(
                    {
                        "bundle_id": "environment-review-bundle-chevron-qA-0001",
                        "file_observation_id": "environment-file-observation-chevron-qA-current",
                        "finding": finding,
                        "basis": "Environment file observation finding family must match classification.",
                        "does_not_claim": does_not_claim,
                    }
                )

                with self.assertRaisesRegex(ValueError, "classification"):
                    build_environment_review_bundle_summary(source)

    def test_file_observation_finding_families_are_accepted_when_classification_matches(
        self,
    ) -> None:
        cases = [
            (
                "environment_files_observed_with_mismatch",
                "environment_file_digest_mismatch",
                {"observed": 2},
                "dependency_resolution_or_file_repair",
            ),
            (
                "environment_files_observed_with_mismatch",
                "environment_file_size_mismatch",
                {"observed": 2},
                "dependency_resolution_or_file_repair",
            ),
            (
                "environment_files_observed_with_review_findings",
                "environment_file_parse_failed",
                {"observed": 2},
                "dependency_resolution_or_runtime_compatibility",
            ),
            (
                "environment_files_unavailable_for_review",
                "environment_file_unavailable",
                {"unavailable": 1},
                "environment_repair_or_dependency_sync",
            ),
        ]
        for classification, finding, status_counts, does_not_claim in cases:
            with self.subTest(classification=classification, finding=finding):
                source = _load_input()
                source["environment_file_observations"][0]["classification"] = classification
                source["environment_file_observations"][0]["observation_status_counts"] = (
                    status_counts
                )
                source["file_observation_findings"].append(
                    {
                        "bundle_id": "environment-review-bundle-chevron-qA-0001",
                        "file_observation_id": "environment-file-observation-chevron-qA-current",
                        "finding": finding,
                        "basis": "Environment file observation finding family matches classification.",
                        "does_not_claim": does_not_claim,
                    }
                )

                summary = build_environment_review_bundle_summary(source)
                file_findings = [
                    item
                    for item in summary["environment_review_findings"]
                    if item["source_kind"] == "environment_file_observation"
                ]

                self.assertEqual(file_findings[0]["finding"], finding)

    def test_file_observation_status_counts_must_match_projected_findings(self) -> None:
        cases = [
            (
                "environment_file_digest_mismatch",
                "environment_files_observed_with_mismatch",
                {"observed": 2, "unavailable": 1},
                "dependency_resolution_or_file_repair",
            ),
            (
                "environment_file_unavailable",
                "environment_files_unavailable_for_review",
                {"observed": 2},
                "environment_repair_or_dependency_sync",
            ),
            (
                "environment_file_digest_mismatch",
                "environment_files_observed_with_mismatch",
                {"observed": 0},
                "dependency_resolution_or_file_repair",
            ),
        ]
        for finding, classification, status_counts, does_not_claim in cases:
            with self.subTest(finding=finding):
                source = _load_input()
                source["environment_file_observations"][0]["classification"] = classification
                source["environment_file_observations"][0]["observation_status_counts"] = (
                    status_counts
                )
                source["file_observation_findings"].append(
                    {
                        "bundle_id": "environment-review-bundle-chevron-qA-0001",
                        "file_observation_id": "environment-file-observation-chevron-qA-current",
                        "finding": finding,
                        "basis": "Environment file observation status does not support the finding.",
                        "does_not_claim": does_not_claim,
                    }
                )

                with self.assertRaisesRegex(ValueError, "status counts"):
                    build_environment_review_bundle_summary(source)

    def test_file_observation_match_classification_rejects_unavailable_status_counts(self) -> None:
        source = _load_input()
        source["environment_file_observations"][0]["observation_status_counts"] = {
            "observed": 1,
            "unavailable": 1,
        }

        with self.assertRaisesRegex(ValueError, "status counts"):
            build_environment_review_bundle_summary(source)

    def test_shared_file_observation_review_finding_count_aggregates_projected_findings(
        self,
    ) -> None:
        source = _load_input()
        source["environment_file_observations"][0]["classification"] = (
            "environment_files_observed_with_mismatch"
        )
        second_bundle = copy.deepcopy(source["review_bundles"][0])
        second_bundle["bundle_id"] = "environment-review-bundle-chevron-qA-0002"
        source["review_bundles"].append(second_bundle)
        for finding in list(source["comparison_findings"]):
            second_finding = copy.deepcopy(finding)
            second_finding["bundle_id"] = "environment-review-bundle-chevron-qA-0002"
            source["comparison_findings"].append(second_finding)
        for finding in list(source["readiness_findings"]):
            second_finding = copy.deepcopy(finding)
            second_finding["bundle_id"] = "environment-review-bundle-chevron-qA-0002"
            source["readiness_findings"].append(second_finding)
        source["file_observation_findings"].append(
            {
                "bundle_id": "environment-review-bundle-chevron-qA-0002",
                "file_observation_id": "environment-file-observation-chevron-qA-current",
                "finding": "environment_file_digest_mismatch",
                "basis": "Observed sha256 digest differs from the declared environment file digest.",
                "does_not_claim": "dependency_resolution_or_file_repair",
            }
        )

        summary = build_environment_review_bundle_summary(source)

        self.assertEqual(len(summary["environment_file_observations"]), 1)
        self.assertEqual(summary["environment_file_observations"][0]["review_finding_count"], 1)
        self.assertEqual(summary["review_bundles"][0]["file_observation_finding_count"], 0)
        self.assertEqual(summary["review_bundles"][1]["file_observation_finding_count"], 1)
        self.assertEqual(summary["finding_source_counts"]["environment_file_observation"], 1)
        self.assertEqual(summary["finding_source_counts"]["environment_comparison"], 8)
        self.assertEqual(summary["finding_source_counts"]["environment_readiness_plan"], 4)

    def test_readiness_plan_must_reference_current_environment(self) -> None:
        source = _load_input()
        source["environment_readiness_plans"][0]["declared_environment_id"] = (
            "declared-environment-chevron-qA-reference"
        )

        with self.assertRaisesRegex(ValueError, "readiness plan"):
            build_environment_review_bundle_summary(source)

    def test_readiness_finding_source_must_match_bundled_readiness_plan(self) -> None:
        source = _load_input()
        source["readiness_findings"][0]["readiness_plan_id"] = "missing-readiness-plan"

        with self.assertRaisesRegex(ValueError, "readiness finding source"):
            build_environment_review_bundle_summary(source)

    def test_readiness_finding_codes_are_bounded(self) -> None:
        source = _load_input()
        source["readiness_findings"][0]["finding"] = "runtime_probe_performed"

        with self.assertRaisesRegex(ValueError, "readiness finding is unsupported"):
            build_environment_review_bundle_summary(source)

    def test_readiness_finding_does_not_claim_is_bounded(self) -> None:
        source = _load_input()
        source["readiness_findings"][0]["does_not_claim"] = "dependency_sync_performed"

        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            build_environment_review_bundle_summary(source)

    def test_readiness_finding_states_are_accepted_when_counts_match(self) -> None:
        cases = [
            ("check_blocked", "run_can_start", "blocked"),
            ("check_unsupported", "supported_environment_operation", "unsupported"),
        ]
        for finding, does_not_claim, state in cases:
            with self.subTest(finding=finding):
                source = _load_input()
                source["environment_readiness_plans"][0]["check_state_counts"] = {
                    "planned": 3,
                    "review_required": 1,
                    state: 1,
                }
                source["readiness_findings"][0]["finding"] = finding
                source["readiness_findings"][0]["does_not_claim"] = does_not_claim

                summary = build_environment_review_bundle_summary(source)

                self.assertEqual(summary["environment_review_findings"][4]["finding"], finding)

    def test_environment_claims_must_remain_non_operational(self) -> None:
        source = _load_input()
        source["environment_contexts"][1]["environment_claims"]["sync_claim"] = "synced"

        with self.assertRaisesRegex(ValueError, "sync_claim"):
            build_environment_review_bundle_summary(source)

    def test_environment_claims_must_not_allow_extra_keys(self) -> None:
        source = _load_input()
        source["environment_contexts"][1]["environment_claims"]["runtime_ready"] = "claimed"

        with self.assertRaisesRegex(ValueError, "claims must match expected shape"):
            build_environment_review_bundle_summary(source)

    def test_environment_claims_must_not_allow_missing_keys(self) -> None:
        source = _load_input()
        del source["environment_contexts"][1]["environment_claims"]["sync_claim"]

        with self.assertRaisesRegex(ValueError, "claims must match expected shape"):
            build_environment_review_bundle_summary(source)

    def test_readiness_plan_must_not_allow_extra_claim_keys(self) -> None:
        source = _load_input()
        source["environment_readiness_plans"][0]["runtime_ready"] = "claimed"

        with self.assertRaisesRegex(ValueError, "readiness plan must match expected shape"):
            build_environment_review_bundle_summary(source)

    def test_readiness_plan_must_not_allow_missing_claim_keys(self) -> None:
        source = _load_input()
        del source["environment_readiness_plans"][0]["sync_claim"]

        with self.assertRaisesRegex(ValueError, "readiness plan must match expected shape"):
            build_environment_review_bundle_summary(source)

    def test_readiness_plan_claims_must_remain_non_operational(self) -> None:
        cases = {
            "readiness_claim": "ready",
            "sync_claim": "synced",
            "execution_claim": "imported",
            "hardware_claim": "probed",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                source = _load_input()
                source["environment_readiness_plans"][0][key] = value

                with self.assertRaisesRegex(ValueError, key):
                    build_environment_review_bundle_summary(source)

    def test_policy_must_not_allow_missing_keys(self) -> None:
        source = _load_input()
        del source["environment_review_bundle_policy"]["summary_policy"]

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_environment_review_bundle_summary(source)

    def test_count_maps_reject_unsupported_states(self) -> None:
        cases = [
            ("environment_comparisons", "finding_state_counts", "executed"),
            ("environment_file_observations", "observation_status_counts", "synced"),
            ("environment_readiness_plans", "check_state_counts", "runtime_ready"),
        ]
        for collection_key, count_key, unsupported_state in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][count_key][unsupported_state] = 1

                with self.assertRaisesRegex(ValueError, "unsupported state"):
                    build_environment_review_bundle_summary(source)

    def test_count_maps_reject_negative_or_bool_counts(self) -> None:
        cases = [
            ("environment_comparisons", "finding_state_counts", "changed", -1),
            ("environment_file_observations", "observation_status_counts", "observed", True),
            ("environment_readiness_plans", "check_state_counts", "planned", 1.25),
        ]
        for collection_key, count_key, state, invalid_count in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][count_key][state] = invalid_count

                with self.assertRaisesRegex(ValueError, "non-negative integers"):
                    build_environment_review_bundle_summary(source)

    def test_scalar_counts_reject_negative_bool_or_non_integer_values(self) -> None:
        cases = [
            ("prepared_run_contexts", "selected_context_count", -1),
            ("environment_comparisons", "fact_count", True),
            ("environment_file_observations", "review_finding_count", 1.25),
            ("environment_readiness_plans", "check_count", "5"),
        ]
        for collection_key, count_key, invalid_count in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][count_key] = invalid_count

                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    build_environment_review_bundle_summary(source)

    def test_aggregate_counts_must_match_count_maps(self) -> None:
        cases = [
            ("environment_comparisons", "fact_count", "finding_state_counts"),
            ("environment_readiness_plans", "check_count", "check_state_counts"),
        ]
        for collection_key, scalar_key, map_key in cases:
            with self.subTest(collection_key=collection_key):
                source = _load_input()
                source[collection_key][0][scalar_key] = (
                    sum(source[collection_key][0][map_key].values()) + 1
                )

                with self.assertRaisesRegex(ValueError, "must match"):
                    build_environment_review_bundle_summary(source)

    def test_comparison_count_map_must_match_detailed_findings(self) -> None:
        source = _load_input()
        source["environment_comparisons"][0]["finding_state_counts"]["changed"] = 0
        source["environment_comparisons"][0]["finding_state_counts"]["same_declared"] = 2

        with self.assertRaisesRegex(ValueError, "finding_state_counts must match findings"):
            build_environment_review_bundle_summary(source)

    def test_readiness_count_map_must_match_detailed_findings(self) -> None:
        source = _load_input()
        source["environment_readiness_plans"][0]["check_state_counts"]["planned"] = 5
        source["environment_readiness_plans"][0]["check_state_counts"]["review_required"] = 0

        with self.assertRaisesRegex(ValueError, "check_state_counts must match findings"):
            build_environment_review_bundle_summary(source)

    def test_expected_output_records_review_summary_boundary_metadata(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-environment-review-bundle-summary.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["candidate_summary"]["environment_review_bundle_policy"]["summary_policy"],
            "review_summary",
        )
        contract_guard = expected["reference_semantics"]["contract_guard"]
        for phrase in [
            "not an environment manager",
            "package resolver",
            "dependency sync operation",
            "package installation step",
            "runtime probe",
            "code import",
            "execution step",
            "hardware check",
            "shared environment schema",
            "managed runner",
            "run-blocking decision",
            "runnable-readiness claim",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract_guard)
        boundary_notes = " ".join(expected["boundary_notes"])
        for phrase in [
            "dependency resolution",
            "dependency sync",
            "package installation",
            "runtime readiness",
            "hardware readiness",
            "code execution",
            "shared environment schema",
            "run-blocking decisions",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, boundary_notes)
                self.assertIn(phrase, expected["decisions_not_earned"])
        self.assertIn("run-start readiness", boundary_notes)
        self.assertIn("runnable readiness", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
