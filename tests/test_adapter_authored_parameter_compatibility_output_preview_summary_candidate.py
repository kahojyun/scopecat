from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.adapter_authored_parameter_compatibility_output_preview import (
    build_adapter_authored_parameter_compatibility_output_preview_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "adapter_authored_parameter_compatibility_output_preview"
    / "basic_preview"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "preview-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-preview-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class AdapterAuthoredParameterCompatibilityOutputPreviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_adapter_authored_parameter_compatibility_output_preview_summary(
            _load_input()
        )

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_adapter_authored_parameter_compatibility_output_preview_summary(source)

        source["adapter_output_manifest"]["entries"][0]["value"] = 0.99
        source["adapter_output_manifest"]["target"]["size_bytes"] = 999

        self.assertEqual(summary["entries"][0]["value"], 0.42)
        self.assertEqual(summary["target"]["size_bytes"], 256)

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["adapter_output_policy"]["file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "file_observation"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_request_summary_must_be_ready(self) -> None:
        source = _load_input()
        source["adapter_request_summary"]["classification"] = "blocked"

        with self.assertRaisesRegex(ValueError, "ready adapter request"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_manifest_identity_must_match_request(self) -> None:
        source = _load_input()
        source["adapter_output_manifest"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter_state_id"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_target_display_must_match_request(self) -> None:
        source = _load_input()
        source["adapter_output_manifest"]["target"]["target_display_label"] = (
            "redacted-other-target"
        )

        with self.assertRaisesRegex(ValueError, "target display"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_available_target_requires_valid_digest_and_size(self) -> None:
        source = _load_input()
        source["adapter_output_manifest"]["target"]["digest"] = "sha256:not-a-digest"

        with self.assertRaisesRegex(ValueError, "digest"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

        source = _load_input()
        source["adapter_output_manifest"]["target"]["size_bytes"] = 0

        with self.assertRaisesRegex(ValueError, "size_bytes"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_unavailable_target_needs_review(self) -> None:
        source = _load_input()
        target = source["adapter_output_manifest"]["target"]
        target["reference_state"] = "adapter_declared_unavailable"
        target.pop("digest")
        target.pop("size_bytes")
        target["reason"] = "Adapter declared no output target was available."

        summary = build_adapter_authored_parameter_compatibility_output_preview_summary(source)

        self.assertEqual(
            summary["classification"],
            "adapter_compatibility_output_needs_target_review",
        )
        self.assertEqual(
            summary["target"]["reason"], "Adapter declared no output target was available."
        )

    def test_entries_must_account_for_requested_adapter_keys(self) -> None:
        source = _load_input()
        source["adapter_output_manifest"]["entries"].pop()

        with self.assertRaisesRegex(ValueError, "every requested adapter_key"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_emitted_entries_must_match_requested_value(self) -> None:
        source = _load_input()
        source["adapter_output_manifest"]["entries"][0]["value"] = 0.99

        with self.assertRaisesRegex(ValueError, "value"):
            build_adapter_authored_parameter_compatibility_output_preview_summary(source)

    def test_skipped_entry_requires_reason_and_marks_ready_with_findings(self) -> None:
        source = _load_input()
        entry = source["adapter_output_manifest"]["entries"][0]
        entry["entry_state"] = "adapter_declared_skipped"
        entry.pop("value")
        entry.pop("unit")
        entry.pop("value_shape")
        entry["reason"] = "Adapter skipped this key by user configuration."

        summary = build_adapter_authored_parameter_compatibility_output_preview_summary(source)

        self.assertEqual(
            summary["classification"],
            "adapter_compatibility_output_ready_with_findings",
        )
        self.assertEqual(
            summary["entries"][0]["reason"], "Adapter skipped this key by user configuration."
        )

    def test_blocking_adapter_finding_blocks_output(self) -> None:
        source = _load_input()
        source["adapter_findings"] = [
            {
                "code": "adapter_output_write_failed",
                "severity": "block_output",
                "message": "Adapter declared that output generation failed.",
            }
        ]

        summary = build_adapter_authored_parameter_compatibility_output_preview_summary(source)

        self.assertEqual(
            summary["classification"],
            "adapter_compatibility_output_blocked_by_adapter_finding",
        )


if __name__ == "__main__":
    unittest.main()
