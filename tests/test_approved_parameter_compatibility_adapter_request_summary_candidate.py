from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.approved_parameter_compatibility_adapter_request import (
    build_approved_parameter_compatibility_adapter_request_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "approved_parameter_compatibility_adapter_request"
    / "basic_request"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "request-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-request-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class ApprovedParameterCompatibilityAdapterRequestSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_approved_parameter_compatibility_adapter_request_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_approved_parameter_compatibility_adapter_request_summary(source)

        source["operator_approval_summary"]["prepared_run_context"]["logical_targets"].append(
            "mutated"
        )
        source["requested_entries"][0]["value"] = 0.99

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(summary["requested_entries"][0]["value"], 0.42)

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["adapter_request_policy"]["adapter_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "adapter_execution"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_operator_approval_must_be_approved(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["classification"] = "operator_pre_run_review_deferred"

        with self.assertRaisesRegex(ValueError, "approved operator pre-run review"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_operator_approval_must_not_have_produced_compatibility_output(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["decision_effects"]["compatibility_output"] = "produced"

        with self.assertRaisesRegex(ValueError, "compatibility output"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_adapter_execution_authority_must_remain_external(self) -> None:
        source = _load_input()
        source["adapter_profile"]["execution_authority"] = "scopecat_core"

        with self.assertRaisesRegex(ValueError, "user-authored external adapter"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_target_profile_must_be_public_safe_and_redacted(self) -> None:
        source = _load_input()
        source["adapter_profile"]["target_profile_id"] = "lab-parameter-json-target"

        with self.assertRaisesRegex(ValueError, "target_profile_id"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_request_must_match_approval_identity(self) -> None:
        source = _load_input()
        source["adapter_request"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter_state_id"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_target_path_authority_must_stay_adapter_or_user_owned(self) -> None:
        source = _load_input()
        source["adapter_request"]["target_hint"]["path_authority"] = "scopecat_owned"

        with self.assertRaisesRegex(ValueError, "path authority"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_entry_count_must_match_trusted_entry_count(self) -> None:
        source = _load_input()
        source["requested_entries"].pop()

        with self.assertRaisesRegex(ValueError, "trusted entry count"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_requested_entries_must_be_trusted_scalar_values(self) -> None:
        source = _load_input()
        source["requested_entries"][0]["trust_status"] = "review_required"

        with self.assertRaisesRegex(ValueError, "trusted"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

        source = _load_input()
        source["requested_entries"][0]["value"] = {"nested": "unsupported"}

        with self.assertRaisesRegex(ValueError, "scalar"):
            build_approved_parameter_compatibility_adapter_request_summary(source)

    def test_duplicate_adapter_keys_are_rejected(self) -> None:
        source = _load_input()
        source["requested_entries"][1]["adapter_key"] = source["requested_entries"][0][
            "adapter_key"
        ]

        with self.assertRaisesRegex(ValueError, "duplicate adapter_key"):
            build_approved_parameter_compatibility_adapter_request_summary(source)


if __name__ == "__main__":
    unittest.main()
