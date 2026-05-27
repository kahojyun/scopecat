from __future__ import annotations

import builtins
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.environment_operation_review_bundle import (
    build_environment_operation_review_bundle_summary,
)
from implementation_candidates.environment_operation_review_bundle.contracts import (
    EXPECTED_POLICY,
    POLICY_ATTENTION_MATRIX,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "environment_operation_review_bundle" / "basic_operation_review"
)
MANIFEST_FIXTURE = (
    ROOT / "tests" / "fixtures" / "modern_manifest_preflight" / "basic_pyproject_preflight"
)
INTENT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"
RESULT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_result" / "basic_uv_sync_result"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "environment-operation-review-input.json").read_text(encoding="utf-8")
    )


def _load_expected() -> dict:
    return json.loads(
        (FIXTURE / "expected-environment-operation-review-summary.json").read_text(encoding="utf-8")
    )


def _load_prior_candidate_summary(fixture_dir: Path, file_name: str) -> dict:
    return json.loads((fixture_dir / file_name).read_text(encoding="utf-8"))["candidate_summary"]


class EnvironmentOperationReviewBundleCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_environment_operation_review_bundle_summary(_load_input())
        expected = _load_expected()["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_expected_output_declares_fixture_boundary_metadata(self) -> None:
        expected = _load_expected()

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(expected["source_fixture"], "environment-operation-review-input.json")
        self.assertEqual(expected["reference_semantics"]["status"], "fixture_only")
        self.assertIn("does not execute uv", expected["reference_semantics"]["contract_guard"])

    def test_successful_external_result_still_has_review_limits(self) -> None:
        summary = build_environment_operation_review_bundle_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["operation_review_status"],
            "external_sync_reported_success_with_review_limits",
        )
        self.assertEqual(summary["operation_review_findings"], [])
        self.assertEqual(
            attention["dependency_sync_externally_reported"]["does_not_claim"],
            "verified_synchronized_environment",
        )
        self.assertEqual(
            attention["runnable_readiness_not_claimed"]["does_not_claim"],
            "run_can_start",
        )

    def test_accepts_full_prior_summary_shapes_as_projection_inputs(self) -> None:
        source = _load_input()
        source["uv_sync_intent_summary"] = _load_prior_candidate_summary(
            INTENT_FIXTURE,
            "expected-uv-sync-intent-summary.json",
        )
        source["uv_sync_result_summary"] = _load_prior_candidate_summary(
            RESULT_FIXTURE,
            "expected-uv-sync-result-summary.json",
        )

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["sync_result_ref"]["result_id"], "uv-sync-result-chevron-qA-001")
        self.assertEqual(
            summary["operation_review_status"],
            "external_sync_reported_success_with_review_limits",
        )
        self.assertEqual(summary["operation_review_findings"], [])

    def test_accepts_full_manifest_shape_and_preserves_manifest_findings(self) -> None:
        source = _load_input()
        source["modern_manifest_preflight_summary"] = _load_prior_candidate_summary(
            MANIFEST_FIXTURE,
            "expected-modern-manifest-preflight-summary.json",
        )
        source["uv_sync_intent_summary"] = _load_prior_candidate_summary(
            INTENT_FIXTURE,
            "expected-uv-sync-intent-summary.json",
        )
        source["uv_sync_result_summary"] = _load_prior_candidate_summary(
            RESULT_FIXTURE,
            "expected-uv-sync-result-summary.json",
        )
        source["operation_review_request"]["manifest_preflight_request_id"] = (
            "modern-manifest-preflight-chevron-qA-0001"
        )

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["sync_result_ref"]["result_id"], "uv-sync-result-chevron-qA-001")
        self.assertIn(
            "manifest_preflight_not_passed",
            [finding["code"] for finding in summary["operation_review_findings"]],
        )
        self.assertIn(
            "manifest_preflight_has_findings",
            [finding["code"] for finding in summary["operation_review_findings"]],
        )
        self.assertIn(
            "declared_environment_mismatch",
            [finding["code"] for finding in summary["operation_review_findings"]],
        )

    def test_bundle_does_not_read_files_probe_filesystem_or_execute(self) -> None:
        source = _load_input()
        with (
            mock.patch.object(Path, "open", side_effect=AssertionError("unexpected file read")),
            mock.patch.object(Path, "exists", side_effect=AssertionError("unexpected exists")),
            mock.patch.object(Path, "is_file", side_effect=AssertionError("unexpected is_file")),
            mock.patch.object(Path, "stat", side_effect=AssertionError("unexpected stat")),
            mock.patch.object(
                Path, "read_text", side_effect=AssertionError("unexpected read_text")
            ),
            mock.patch.object(builtins, "open", side_effect=AssertionError("unexpected open")),
            mock.patch.object(os, "stat", side_effect=AssertionError("unexpected os.stat")),
            mock.patch.object(os, "scandir", side_effect=AssertionError("unexpected os.scandir")),
            mock.patch.object(os, "listdir", side_effect=AssertionError("unexpected os.listdir")),
            mock.patch.object(
                subprocess, "run", side_effect=AssertionError("unexpected subprocess.run")
            ),
            mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("unexpected subprocess.Popen")
            ),
            mock.patch.object(
                subprocess, "call", side_effect=AssertionError("unexpected subprocess.call")
            ),
            mock.patch.object(
                subprocess,
                "check_call",
                side_effect=AssertionError("unexpected subprocess.check_call"),
            ),
            mock.patch.object(
                subprocess,
                "check_output",
                side_effect=AssertionError("unexpected subprocess.check_output"),
            ),
            mock.patch.object(os, "system", side_effect=AssertionError("unexpected os.system")),
            mock.patch.object(os, "popen", side_effect=AssertionError("unexpected os.popen")),
        ):
            summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(
            summary["operation_review_status"],
            "external_sync_reported_success_with_review_limits",
        )

    def test_policy_attention_matrix_covers_explicit_policy_boundaries(self) -> None:
        expected_policy_keys = set(EXPECTED_POLICY) - {
            "manifest_preflight_source",
            "sync_intent_source",
            "sync_result_source",
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

    def test_policy_overrides_are_rejected_for_all_policy_keys(self) -> None:
        for key, expected in EXPECTED_POLICY.items():
            with self.subTest(key=key):
                source = _load_input()
                source["environment_operation_review_policy"][key] = f"not-{expected}"

                with self.assertRaisesRegex(ValueError, key):
                    build_environment_operation_review_bundle_summary(source)

    def test_manifest_preflight_findings_are_review_findings(self) -> None:
        source = _load_input()
        source["modern_manifest_preflight_summary"]["preflight_status"] = (
            "manifest_preflight_has_review_findings"
        )
        source["modern_manifest_preflight_summary"]["preflight_findings"] = [
            {
                "code": "declared_dependency_group_missing",
                "severity": "review",
                "basis": "Declared dependency group lab is absent.",
                "does_not_claim": "dependency_resolution_or_dependency_sync",
            }
        ]

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["manifest_preflight_not_passed", "manifest_preflight_has_findings"],
        )

    def test_non_passing_manifest_preflight_status_is_review_finding(self) -> None:
        source = _load_input()
        source["modern_manifest_preflight_summary"]["preflight_status"] = (
            "manifest_preflight_has_review_findings"
        )

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["manifest_preflight_not_passed"],
        )

    def test_unsupported_manifest_preflight_status_is_rejected(self) -> None:
        source = _load_input()
        source["modern_manifest_preflight_summary"]["preflight_status"] = (
            "manifest_preflight_ready_for_review"
        )

        with self.assertRaisesRegex(ValueError, "preflight_status is unsupported"):
            build_environment_operation_review_bundle_summary(source)

    def test_sync_result_failure_is_review_finding_not_verified_sync(self) -> None:
        source = _load_input()
        source["uv_sync_result_summary"]["command_result"]["execution_state"] = "completed_failed"
        source["uv_sync_result_summary"]["command_result"]["exit_code"] = 1
        source["uv_sync_result_summary"]["result_status"] = "external_sync_reported_failure"
        source["uv_sync_result_summary"]["result_findings"] = [
            {
                "code": "uv_sync_reported_failure",
                "severity": "review",
                "basis": "External uv sync result reports a non-zero exit code.",
                "does_not_claim": "synchronized_or_installed_environment",
            }
        ]

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_result_has_findings", "uv_sync_result_not_success"],
        )

    def test_cross_summary_mismatch_is_review_finding(self) -> None:
        source = _load_input()
        source["uv_sync_result_summary"]["command_result"]["argv"] = ["uv", "sync", "--locked"]

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["sync_result_command_mismatch"],
        )

    def test_result_intent_ref_mismatch_is_review_finding(self) -> None:
        source = _load_input()
        source["uv_sync_result_summary"]["uv_sync_intent_ref"]["request_id"] = (
            "uv-sync-intent-other"
        )
        source["uv_sync_result_summary"]["uv_sync_intent_ref"]["command_intent"]["argv"] = [
            "uv",
            "sync",
            "--locked",
            "--no-default-groups",
            "--group",
            "default",
        ]

        summary = build_environment_operation_review_bundle_summary(source)

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["sync_result_intent_ref_mismatch"],
        )

    def test_inconsistent_result_status_and_execution_facts_are_rejected(self) -> None:
        source = _load_input()
        source["uv_sync_result_summary"]["command_result"]["execution_state"] = "completed_failed"
        source["uv_sync_result_summary"]["command_result"]["exit_code"] = 1

        with self.assertRaisesRegex(ValueError, "success status"):
            build_environment_operation_review_bundle_summary(source)

    def test_bounded_child_command_facts_are_enforced(self) -> None:
        cases = [
            (
                ("uv_sync_intent_summary", "command_intent", "argv"),
                ["uv", "sync", "--upgrade"],
                "bounded uv sync intent argv",
            ),
            (
                ("uv_sync_result_summary", "uv_sync_intent_ref", "command_intent", "argv"),
                ["uv", "sync", "--upgrade"],
                "bounded uv sync intent argv",
            ),
            (
                ("uv_sync_result_summary", "command_result", "working_directory"),
                "/workspace/project",
                "relative command directory",
            ),
        ]
        for path, value, message in cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_environment_operation_review_bundle_summary(source)

    def test_alignment_finding_paths_are_explicit(self) -> None:
        cases = [
            (
                ("operation_review_request", "manifest_preflight_request_id"),
                "modern-manifest-preflight-other",
                ["manifest_preflight_request_mismatch"],
            ),
            (
                ("operation_review_request", "sync_intent_request_id"),
                "uv-sync-intent-other",
                ["sync_intent_request_mismatch"],
            ),
            (
                ("operation_review_request", "sync_result_id"),
                "uv-sync-result-other",
                ["sync_result_id_mismatch"],
            ),
            (
                (
                    "modern_manifest_preflight_summary",
                    "preflight_request",
                    "prepared_run_context_id",
                ),
                "prepared-run-context-other",
                ["prepared_run_context_mismatch"],
            ),
            (
                (
                    "modern_manifest_preflight_summary",
                    "preflight_request",
                    "declared_environment_id",
                ),
                "declared-env-other",
                ["declared_environment_mismatch"],
            ),
            (
                ("uv_sync_result_summary", "command_result", "intent_request_id"),
                "uv-sync-intent-other",
                ["sync_result_intent_mismatch"],
            ),
            (
                ("uv_sync_result_summary", "command_result", "argv"),
                ["uv", "sync", "--locked"],
                ["sync_result_command_mismatch"],
            ),
        ]
        for path, value, expected_codes in cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                summary = build_environment_operation_review_bundle_summary(source)

                self.assertEqual(
                    [finding["code"] for finding in summary["operation_review_findings"]],
                    expected_codes,
                )

    def test_unsupported_manager_is_rejected_before_composition(self) -> None:
        source = _load_input()
        source["operation_review_request"]["expected_manager"] = "pixi"

        with self.assertRaisesRegex(ValueError, "supports uv only"):
            build_environment_operation_review_bundle_summary(source)
