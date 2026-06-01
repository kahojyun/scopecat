from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.measurement_context import (
    ResolvedContextLinkComparisonRequest,
    build_resolved_context_link_comparison_summary,
    compare_resolved_context_links,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "resolved_context_link_comparison" / "basic_selected_reference"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


class MeasurementContextEngineeringPrototypeTest(unittest.TestCase):
    def test_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        request = ResolvedContextLinkComparisonRequest.from_dict(source)
        result = compare_resolved_context_links(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(FIXTURE / "expected-resolved-context-comparison-summary.json"),
        )
        self.assertEqual(result.comparison["reference_mark_label"], "last-working")
        self.assertEqual(
            build_resolved_context_link_comparison_summary(source),
            result.to_dict(),
        )

    def test_rejects_intent_selector_comparison_expansion(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        source["comparison_request"]["comparison_scope"] = ["measurement_intent_selectors"]

        with self.assertRaisesRegex(ValueError, "resolved context-link boundary"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_payload_comparison_expansion(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        source["context_records"][0]["payload_handling"] = "payload_opened_and_compared"

        with self.assertRaisesRegex(ValueError, "payload handling must remain family-owned"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_required_context_for_record_validity(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        source["measurements"][0]["context_links"][0]["required_for_record_validity"] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record validity"):
            ResolvedContextLinkComparisonRequest.from_dict(source)

    def test_rejects_missing_optional_context_without_reason(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        current_environment = source["measurements"][1]["context_links"][3]
        current_environment.pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "requires a missing_reason"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_private_or_path_shaped_ids(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        source["context_records"][0]["context_id"] = "/Users/lab/private/param-state"

        with self.assertRaisesRegex(ValueError, "context id must be public-safe"):
            build_resolved_context_link_comparison_summary(source)

    def test_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(FIXTURE / "resolved-context-comparison-input.json")
        original = copy.deepcopy(source)
        result = compare_resolved_context_links(
            ResolvedContextLinkComparisonRequest.from_dict(source)
        )
        summary = result.to_dict()

        source["comparison_request"]["reference_selection"]["mark_label"] = "mutated"
        summary["comparison"]["reference_mark_label"] = "mutated"

        self.assertEqual(result.comparison["reference_mark_label"], "last-working")
        self.assertEqual(result.to_dict()["not_compared_scope"][0], "measurement_intent_selectors")
        self.assertNotEqual(source, original)


if __name__ == "__main__":
    unittest.main()
