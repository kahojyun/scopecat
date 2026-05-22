from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.comparable_code_surface import (
    build_comparable_code_surface_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "comparable_code_surface" / "recorded_to_managed"


def _load_input() -> dict:
    return json.loads((FIXTURE / "code-surface-comparison-input.json").read_text(encoding="utf-8"))


class ComparableCodeSurfaceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_comparable_code_surface_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-code-surface-comparison-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_comparison_reports_expected_objective_findings(self) -> None:
        summary = build_comparable_code_surface_summary(_load_input())
        findings_by_path = {item["path"]: item for item in summary["code_file_findings"]}

        self.assertEqual(findings_by_path["analysis/run_chevron.py"]["finding"], "same_observed")
        self.assertEqual(findings_by_path["helpers/pulse_shapes.py"]["finding"], "changed")
        self.assertEqual(findings_by_path["helpers/transient_marker.py"]["finding"], "missing")
        self.assertEqual(findings_by_path["notebooks/session_setup.ipynb"]["finding"], "unverified")
        self.assertEqual(findings_by_path["secrets/device_config.py"]["finding"], "redacted")
        self.assertEqual(findings_by_path["legacy/manual_patch.py"]["finding"], "not_compared")
        self.assertEqual(findings_by_path["scripts/old_calibration.py"]["finding"], "missing")
        self.assertEqual(findings_by_path["scripts/new_calibration.py"]["finding"], "missing")

    def test_comparison_summary_counts_findings_without_semantic_claims(self) -> None:
        summary = build_comparable_code_surface_summary(_load_input())
        comparison = summary["comparison_sets"][0]

        self.assertEqual(comparison["compared_path_count"], 8)
        self.assertEqual(
            comparison["finding_counts"],
            {
                "changed": 1,
                "missing": 3,
                "not_compared": 1,
                "redacted": 1,
                "same_observed": 1,
                "unverified": 1,
            },
        )
        changed = [item for item in summary["code_file_findings"] if item["finding"] == "changed"][
            0
        ]
        declared_missing = [
            item
            for item in summary["code_file_findings"]
            if item["path"] == "helpers/transient_marker.py"
        ][0]
        self.assertEqual(changed["does_not_claim"], "semantic_source_diff_or_cause_attribution")
        self.assertEqual(declared_missing["baseline_capture_state"], "missing")
        self.assertEqual(declared_missing["comparison_capture_state"], "content_captured")
        self.assertEqual(declared_missing["does_not_claim"], "content_equality_or_difference")

    def test_attention_records_boundary_deferrals(self) -> None:
        summary = build_comparable_code_surface_summary(_load_input())
        source = _load_input()

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            source["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["comparison_policy"]["semantic_source_diff"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "semantic_source_diff"):
            build_comparable_code_surface_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["comparison_policy"]["restore_contract"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected comparison policy shape"):
            build_comparable_code_surface_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_comparable_code_surface_summary(source)

        source["comparison_policy"]["content_comparison"] = "mutated"
        source["code_surfaces"][0]["file_facts"][0]["content_state"]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        self.assertEqual(
            summary["comparison_policy"]["content_comparison"],
            "digest_and_capture_state_only",
        )
        self.assertEqual(
            summary["file_facts"][0]["digest"],
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        )

    def test_duplicate_surface_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["code_surfaces"][0])
        source["code_surfaces"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate surface_id"):
            build_comparable_code_surface_summary(source)

    def test_duplicate_file_paths_are_rejected(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][1]["path"] = "analysis/run_chevron.py"

        with self.assertRaisesRegex(ValueError, "duplicate path"):
            build_comparable_code_surface_summary(source)

    def test_comparison_must_reference_known_surfaces(self) -> None:
        source = _load_input()
        source["comparison_sets"][0]["comparison_surface_id"] = "missing-surface"

        with self.assertRaisesRegex(ValueError, "missing comparison surface"):
            build_comparable_code_surface_summary(source)

    def test_comparison_must_use_distinct_surfaces(self) -> None:
        source = _load_input()
        source["comparison_sets"][0]["comparison_surface_id"] = source["comparison_sets"][0][
            "baseline_surface_id"
        ]

        with self.assertRaisesRegex(ValueError, "distinct code surfaces"):
            build_comparable_code_surface_summary(source)

    def test_file_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0]["path"] = "/private/path.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            build_comparable_code_surface_summary(source)

    def test_backslash_paths_are_rejected(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0]["path"] = "analysis\\run.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            build_comparable_code_surface_summary(source)

    def test_content_captured_files_require_integrity_hint(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0].pop("content_state")

        with self.assertRaisesRegex(ValueError, "require content_state"):
            build_comparable_code_surface_summary(source)

    def test_non_content_captured_files_must_not_carry_integrity_hint(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][2]["content_state"] = {
            "digest_algorithm": "sha256",
            "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "size_bytes": 1,
            "observed_at": "2026-05-21T12:00:00Z",
        }

        with self.assertRaisesRegex(ValueError, "must not carry content_state"):
            build_comparable_code_surface_summary(source)

    def test_digest_algorithm_must_be_sha256(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0]["content_state"]["digest_algorithm"] = "md5"

        with self.assertRaisesRegex(ValueError, "must use sha256"):
            build_comparable_code_surface_summary(source)

    def test_integrity_hints_must_use_sha256_hex_digest(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0]["content_state"]["digest"] = (
            "sha256:not-a-real-digest"
        )

        with self.assertRaisesRegex(ValueError, "sha256-prefixed hex digest"):
            build_comparable_code_surface_summary(source)

    def test_unsupported_capture_states_are_rejected(self) -> None:
        source = _load_input()
        source["code_surfaces"][0]["file_facts"][0]["capture_state"] = "unknown"

        with self.assertRaisesRegex(ValueError, "unsupported code capture state"):
            build_comparable_code_surface_summary(source)
