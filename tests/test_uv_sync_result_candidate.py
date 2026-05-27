from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.uv_sync_result import build_uv_sync_result_summary
from implementation_candidates.uv_sync_result.contracts import (
    EXPECTED_POLICY,
    POLICY_ATTENTION_MATRIX,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_result" / "basic_uv_sync_result"
INTENT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"


def _load_input() -> dict:
    return json.loads((FIXTURE / "uv-sync-result-input.json").read_text(encoding="utf-8"))


def _load_intent_summary() -> dict:
    return json.loads(
        (INTENT_FIXTURE / "expected-uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class UvSyncResultCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_uv_sync_result_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-uv-sync-result-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_expected_output_declares_fixture_boundary_metadata(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-uv-sync-result-summary.json").read_text(encoding="utf-8")
        )

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(expected["source_fixture"], "uv-sync-result-input.json")
        self.assertEqual(expected["reference_semantics"]["status"], "fixture_only")
        self.assertIn("review-summary record", expected["reference_semantics"]["contract_guard"])

    def test_success_result_records_external_report_without_readiness_claim(self) -> None:
        summary = build_uv_sync_result_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["result_status"], "external_sync_reported_success")
        self.assertEqual(summary["command_result"]["execution_state"], "completed_success")
        self.assertEqual(summary["command_result"]["exit_code"], 0)
        self.assertEqual(summary["result_findings"], [])
        self.assertEqual(
            attention["dependency_sync_externally_reported"]["does_not_claim"],
            "verified_synchronized_environment",
        )
        self.assertEqual(
            attention["runnable_readiness_not_claimed"]["does_not_claim"],
            "run_can_start",
        )

    def test_accepts_full_uv_sync_intent_summary_projection(self) -> None:
        source = _load_input()
        source["uv_sync_intent_summary"] = _load_intent_summary()

        summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "external_sync_reported_success")
        self.assertEqual(
            summary["uv_sync_intent_ref"]["command_intent"]["argv"],
            source["command_result"]["argv"],
        )
        self.assertNotIn("declared_environment", summary["uv_sync_intent_ref"])

    def test_local_execution_cwd_preserves_absolute_local_review_fact(self) -> None:
        source = _load_input()
        source["command_result"]["local_execution_cwd"] = "/workspace/project"

        summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "external_sync_reported_success")
        self.assertEqual(
            summary["command_result"]["local_execution_cwd"],
            "/workspace/project",
        )

    def test_result_does_not_read_files_probe_filesystem_or_execute(self) -> None:
        source = _load_input()
        with (
            mock.patch.object(Path, "open", side_effect=AssertionError("unexpected file read")),
            mock.patch.object(Path, "exists", side_effect=AssertionError("unexpected exists")),
            mock.patch.object(Path, "is_file", side_effect=AssertionError("unexpected is_file")),
            mock.patch.object(Path, "stat", side_effect=AssertionError("unexpected stat")),
            mock.patch.object(os, "stat", side_effect=AssertionError("unexpected os.stat")),
            mock.patch.object(
                subprocess, "run", side_effect=AssertionError("unexpected subprocess.run")
            ),
            mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("unexpected subprocess.Popen")
            ),
            mock.patch.object(os, "system", side_effect=AssertionError("unexpected os.system")),
        ):
            summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "external_sync_reported_success")

    def test_policy_attention_matrix_covers_explicit_policy_boundaries(self) -> None:
        expected_policy_keys = {
            "summary_policy",
            "result_authority",
            "prior_intent_source",
            "manager_scope",
            "command_result_shape",
            "local_execution_cwd_authority",
            "scopecat_process_execution",
            "manifest_read",
            "lockfile_read",
            "output_parsing",
            "dependency_resolution",
            "dependency_sync",
            "package_install",
            "runtime_probe",
            "code_import_execution",
            "hardware_probe",
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

    def test_policy_overrides_are_rejected_for_all_policy_keys(self) -> None:
        for key, expected in EXPECTED_POLICY.items():
            with self.subTest(key=key):
                source = _load_input()
                source["uv_sync_result_policy"][key] = f"not-{expected}"

                with self.assertRaisesRegex(ValueError, key):
                    build_uv_sync_result_summary(source)

    def test_failed_result_reports_review_finding(self) -> None:
        source = _load_input()
        source["command_result"]["execution_state"] = "completed_failed"
        source["command_result"]["exit_code"] = 1
        source["command_result"]["stderr_summary"] = "uv reported lockfile mismatch"

        summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "external_sync_reported_failure")
        self.assertEqual(
            [finding["code"] for finding in summary["result_findings"]],
            ["uv_sync_reported_failure"],
        )

    def test_not_run_result_carries_no_execution_facts(self) -> None:
        source = _load_input()
        source["command_result"]["execution_state"] = "not_run"
        source["command_result"]["exit_code"] = None
        source["command_result"]["started_at"] = None
        source["command_result"]["completed_at"] = None
        source["command_result"]["duration_ms"] = None
        source["command_result"]["stdout_summary"] = ""

        summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "external_sync_not_run")
        self.assertEqual(
            [finding["code"] for finding in summary["result_findings"]],
            ["uv_sync_not_run"],
        )

        source["command_result"]["exit_code"] = 0
        with self.assertRaisesRegex(ValueError, "not_run"):
            build_uv_sync_result_summary(source)

    def test_result_command_mismatch_is_recorded_as_review_finding(self) -> None:
        source = _load_input()
        source["command_result"]["argv"] = ["uv", "sync", "--locked"]

        summary = build_uv_sync_result_summary(source)

        self.assertEqual(summary["result_status"], "result_requires_review")
        self.assertEqual(
            [finding["code"] for finding in summary["result_findings"]],
            ["result_command_mismatch"],
        )

    def test_result_must_reference_intent_request_and_approval(self) -> None:
        source = _load_input()
        source["command_result"]["intent_request_id"] = "uv-sync-intent-other"

        with self.assertRaisesRegex(ValueError, "request_id"):
            build_uv_sync_result_summary(source)

        source = _load_input()
        source["command_result"]["approval_id"] = "approval-other"

        with self.assertRaisesRegex(ValueError, "approval_id"):
            build_uv_sync_result_summary(source)

    def test_prior_intent_request_and_command_facts_must_be_consistent(self) -> None:
        source = _load_input()
        source["uv_sync_intent_summary"]["command_intent"]["working_directory"] = "other-project"

        with self.assertRaisesRegex(ValueError, "working_directory"):
            build_uv_sync_result_summary(source)

        source = _load_input()
        source["uv_sync_intent_summary"]["sync_request"]["expected_manager"] = "pixi"

        with self.assertRaisesRegex(ValueError, "supports uv only"):
            build_uv_sync_result_summary(source)

    def test_prior_intent_argv_must_keep_bounded_uv_sync_shape(self) -> None:
        source = _load_input()
        source["uv_sync_intent_summary"]["command_intent"]["argv"] = [
            "uv",
            "sync",
            "--upgrade",
        ]

        with self.assertRaisesRegex(ValueError, "bounded uv sync intent argv"):
            build_uv_sync_result_summary(source)

    def test_command_working_directory_remains_relative_command_fact(self) -> None:
        source = _load_input()
        source["command_result"]["working_directory"] = "/workspace/project"

        with self.assertRaisesRegex(ValueError, "relative command directory"):
            build_uv_sync_result_summary(source)

    def test_stdout_and_stderr_are_bounded_summary_text(self) -> None:
        source = _load_input()
        source["command_result"]["stdout_summary"] = "x" * 241

        with self.assertRaisesRegex(ValueError, "stdout_summary"):
            build_uv_sync_result_summary(source)

        source = _load_input()
        source["command_result"]["stderr_summary"] = "line one\nline two"

        with self.assertRaisesRegex(ValueError, "stderr_summary"):
            build_uv_sync_result_summary(source)

    def test_completed_state_and_exit_code_must_agree(self) -> None:
        source = _load_input()
        source["command_result"]["execution_state"] = "completed_success"
        source["command_result"]["exit_code"] = 2

        with self.assertRaisesRegex(ValueError, "completed_success"):
            build_uv_sync_result_summary(source)

        source = _load_input()
        source["command_result"]["execution_state"] = "completed_failed"
        source["command_result"]["exit_code"] = 0

        with self.assertRaisesRegex(ValueError, "completed_failed"):
            build_uv_sync_result_summary(source)

    def test_completed_timestamps_must_be_ordered(self) -> None:
        source = _load_input()
        source["command_result"]["completed_at"] = "2026-05-27T09:29:59Z"

        with self.assertRaisesRegex(ValueError, "completed_at"):
            build_uv_sync_result_summary(source)

    def test_completed_duration_must_match_timestamps(self) -> None:
        source = _load_input()
        source["command_result"]["duration_ms"] = 1

        with self.assertRaisesRegex(ValueError, "duration_ms"):
            build_uv_sync_result_summary(source)

    def test_output_capture_channels_are_bounded(self) -> None:
        for channel in ("stdout", "stderr", "raw_output"):
            with self.subTest(channel=channel):
                source = _load_input()
                source["command_result"]["output_capture"][channel] = "recorded"

                with self.assertRaisesRegex(ValueError, channel):
                    build_uv_sync_result_summary(source)
