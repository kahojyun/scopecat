from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.selected_reference import (
    SelectedReferenceCodeContextComparisonRequest,
    SelectedReferenceComparisonRequest,
    build_selected_reference_code_context_summary,
    build_selected_reference_context_summary,
    compare_selected_reference_code_context,
    compare_selected_reference_context,
)

ROOT = Path(__file__).resolve().parents[1]
BASIC_FIXTURE = (
    ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "basic_context_compare"
)
CODE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "selected_reference_comparison" / "code_context_compare"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


class SelectedReferenceEngineeringPrototypeTest(unittest.TestCase):
    def test_basic_context_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(BASIC_FIXTURE / "reference-comparison-input.json")
        request = SelectedReferenceComparisonRequest.from_dict(source)
        result = compare_selected_reference_context(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(BASIC_FIXTURE / "expected-reference-comparison-summary.json"),
        )
        self.assertEqual(result.comparison["reference_mark_label"], "last_working_reference")
        self.assertEqual(build_selected_reference_context_summary(source), result.to_dict())

    def test_code_context_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(CODE_FIXTURE / "reference-code-comparison-input.json")
        request = SelectedReferenceCodeContextComparisonRequest.from_dict(source)
        result = compare_selected_reference_code_context(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(CODE_FIXTURE / "expected-reference-code-comparison-summary.json"),
        )
        self.assertIn(
            "changed_recorded_code_context",
            {finding["code"] for finding in result.findings},
        )
        self.assertEqual(
            build_selected_reference_code_context_summary(source),
            result.to_dict(),
        )

    def test_basic_context_rejects_code_context_expansion(self) -> None:
        source = _read_json(BASIC_FIXTURE / "reference-comparison-input.json")
        for measurement in source["measurements"]:
            measurement["inputs"].append(
                {
                    "name": "code_context",
                    "snapshot_id": "code-context-out-of-scope",
                    "role": "recorded_entrypoint_and_included_files",
                }
            )

        with self.assertRaisesRegex(ValueError, "must not compare code context"):
            SelectedReferenceComparisonRequest.from_dict(source)

    def test_basic_context_rejects_private_or_path_shaped_identifiers(self) -> None:
        source = _read_json(BASIC_FIXTURE / "reference-comparison-input.json")
        source["measurements"][0]["measurement_id"] = "/Users/lab/private/measurement"
        source["comparison_request"]["reference_measurement_id"] = "/Users/lab/private/measurement"

        with self.assertRaisesRegex(ValueError, "measurement id must be public-safe"):
            build_selected_reference_context_summary(source)

    def test_code_context_rejects_git_or_execution_claim_expansion(self) -> None:
        source = _read_json(CODE_FIXTURE / "reference-code-comparison-input.json")
        source["recorded_code_contexts"][0]["recording_policy"]["internal_git_inspection"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "no-Git/no-dependency boundary"):
            build_selected_reference_code_context_summary(source)

        source = _read_json(CODE_FIXTURE / "reference-code-comparison-input.json")
        source["recorded_code_contexts"][0]["execution_claim"] = "executed_by_scopecat"

        with self.assertRaisesRegex(ValueError, "must not claim execution"):
            build_selected_reference_code_context_summary(source)

    def test_code_context_requires_public_safe_redacted_external_root_display(self) -> None:
        source = _read_json(CODE_FIXTURE / "reference-code-comparison-input.json")
        source["recorded_code_contexts"][0]["external_root_display"] = "/Users/lab/private/code"

        with self.assertRaisesRegex(ValueError, "public-safe and redacted"):
            SelectedReferenceCodeContextComparisonRequest.from_dict(source)

    def test_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(BASIC_FIXTURE / "reference-comparison-input.json")
        original = copy.deepcopy(source)
        result = compare_selected_reference_context(
            SelectedReferenceComparisonRequest.from_dict(source)
        )
        summary = result.to_dict()

        source["comparison_request"]["not_compared_scope"][0] = "mutated"
        summary["comparison"]["reference_mark_label"] = "mutated"

        self.assertEqual(result.comparison["reference_mark_label"], "last_working_reference")
        self.assertEqual(result.to_dict()["not_compared_scope"][0], "fit_quality")
        self.assertNotEqual(source, original)


if __name__ == "__main__":
    unittest.main()
