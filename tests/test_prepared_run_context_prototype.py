from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.prepared_run import (
    PreparedRunContextRequest,
    build_prepared_run_context_summary,
    compose_prepared_run_context,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_context" / "basic_preparation"


def _load_input() -> dict:
    return json.loads((FIXTURE / "prepared-run-context-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads(
        (FIXTURE / "expected-prepared-run-context-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class PreparedRunContextPrototypeTest(unittest.TestCase):
    def test_raw_adapter_matches_validated_candidate_output(self) -> None:
        self.assertEqual(build_prepared_run_context_summary(_load_input()), _expected_candidate())

    def test_typed_request_result_round_trip_matches_raw_adapter(self) -> None:
        source = _load_input()
        request = PreparedRunContextRequest.from_dict(source)
        result = compose_prepared_run_context(request)

        self.assertEqual(result.to_dict(), build_prepared_run_context_summary(source))
        self.assertEqual(
            result.prepared_run_contexts[0]["prepared_run_context_id"],
            "prepared-run-context-chevron-qA-0001",
        )

    def test_output_does_not_alias_input_or_result_dicts(self) -> None:
        source = _load_input()
        result = compose_prepared_run_context(PreparedRunContextRequest.from_dict(source))
        summary = result.to_dict()

        source["context_records"][0]["declared_summary"]["logical_targets"].append("qB")
        summary["prepared_run_contexts"][0]["label"] = "mutated"

        self.assertEqual(
            result.to_dict()["context_records"][0]["declared_summary"]["logical_targets"],
            ["qA", "cAB"],
        )
        self.assertEqual(
            result.prepared_run_contexts[0]["label"],
            "qA chevron manual run context",
        )

    def test_required_unavailable_context_is_a_review_finding_not_run_control(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][-1]["required"] = True

        summary = build_prepared_run_context_summary(source)

        self.assertEqual(
            summary["missing_context_findings"][0]["finding"],
            "required_context_unavailable",
        )
        self.assertEqual(
            summary["missing_context_findings"][0]["does_not_claim"],
            "run_is_blocked_or_unsafe",
        )
        self.assertEqual(
            summary["prepared_run_context_policy"]["hardware_control"],
            "not_performed",
        )
        self.assertEqual(
            summary["prepared_run_context_policy"]["code_import_execution"],
            "not_performed",
        )

    def test_workspace_observation_review_findings_are_not_readiness_claims(self) -> None:
        summary = build_prepared_run_context_summary(_load_input())
        finding = summary["workspace_context_findings"][0]

        self.assertEqual(finding["finding"], "workspace_observation_has_review_findings")
        self.assertEqual(
            finding["does_not_claim"],
            "run_is_blocked_or_workspace_is_unusable",
        )
        self.assertEqual(
            summary["prepared_run_context_policy"]["readiness_claim"],
            "selection_and_workspace_observation_only",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["prepared_run_context_policy"]["environment_sync"] = "performed"

        with self.assertRaisesRegex(ValueError, "environment_sync"):
            build_prepared_run_context_summary(source)

    def test_selected_context_references_must_resolve(self) -> None:
        source = _load_input()
        source["prepared_run_contexts"][0]["selected_contexts"][1]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing selected context"):
            build_prepared_run_context_summary(source)

    def test_workspace_observation_must_align_to_selected_managed_version(self) -> None:
        source = _load_input()
        source["context_records"][5]["declared_summary"]["selected_version_id"] = (
            "managed-code-version-other"
        )

        with self.assertRaisesRegex(ValueError, "selected managed code version"):
            build_prepared_run_context_summary(source)

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        source["context_records"].append(copy.deepcopy(source["context_records"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_prepared_run_context_summary(source)


if __name__ == "__main__":
    unittest.main()
