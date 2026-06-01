from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.measurement_context import (
    MeasurementContextLinkRequest,
    ResolvedContextLinkComparisonRequest,
    SupportingEvidenceReferenceRequest,
    build_measurement_context_link_summary,
    build_resolved_context_link_comparison_summary,
    build_supporting_evidence_reference_summary,
    compare_resolved_context_links,
    summarize_measurement_context_links,
    summarize_supporting_evidence_reference,
)

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_FIXTURE = (
    ROOT / "tests" / "fixtures" / "resolved_context_link_comparison" / "basic_selected_reference"
)
CONTEXT_LINK_FIXTURE = (
    ROOT / "tests" / "fixtures" / "measurement_context_link" / "basic_optional_links"
)
SUPPORTING_EVIDENCE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "supporting_evidence_reference"
    / "basic_supporting_evidence_reference"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


class MeasurementContextEngineeringPrototypeTest(unittest.TestCase):
    def test_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        request = ResolvedContextLinkComparisonRequest.from_dict(source)
        result = compare_resolved_context_links(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(
                COMPARISON_FIXTURE / "expected-resolved-context-comparison-summary.json"
            ),
        )
        self.assertEqual(result.comparison["reference_mark_label"], "last-working")
        self.assertEqual(
            build_resolved_context_link_comparison_summary(source),
            result.to_dict(),
        )

    def test_rejects_intent_selector_comparison_expansion(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        source["comparison_request"]["comparison_scope"] = ["measurement_intent_selectors"]

        with self.assertRaisesRegex(ValueError, "resolved context-link boundary"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_payload_comparison_expansion(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        source["context_records"][0]["payload_handling"] = "payload_opened_and_compared"

        with self.assertRaisesRegex(ValueError, "payload handling must remain family-owned"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_required_context_for_record_validity(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        source["measurements"][0]["context_links"][0]["required_for_record_validity"] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record validity"):
            ResolvedContextLinkComparisonRequest.from_dict(source)

    def test_rejects_missing_optional_context_without_reason(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        current_environment = source["measurements"][1]["context_links"][3]
        current_environment.pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "requires a missing_reason"):
            build_resolved_context_link_comparison_summary(source)

    def test_rejects_private_or_path_shaped_ids(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
        source["context_records"][0]["context_id"] = "/Users/lab/private/param-state"

        with self.assertRaisesRegex(ValueError, "context id must be public-safe"):
            build_resolved_context_link_comparison_summary(source)

    def test_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(COMPARISON_FIXTURE / "resolved-context-comparison-input.json")
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

    def test_context_link_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(CONTEXT_LINK_FIXTURE / "context-link-input.json")
        request = MeasurementContextLinkRequest.from_dict(source)
        result = summarize_measurement_context_links(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(CONTEXT_LINK_FIXTURE / "expected-context-link-summary.json"),
        )
        self.assertEqual(result.measurement_records[0]["context_link_count"], 0)
        self.assertEqual(result.linked_context_refs[0]["context_id"], "param-state-0007")
        self.assertEqual(
            build_measurement_context_link_summary(source),
            result.to_dict(),
        )

    def test_context_link_rejects_policy_expansion(self) -> None:
        source = _read_json(CONTEXT_LINK_FIXTURE / "context-link-input.json")
        source["context_link_policy"]["context_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "context_import"):
            build_measurement_context_link_summary(source)

    def test_context_link_rejects_required_context_for_record_validity(self) -> None:
        source = _read_json(CONTEXT_LINK_FIXTURE / "context-link-input.json")
        source["measurement_records"][1]["context_links"][0]["required_for_record_validity"] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record validity"):
            MeasurementContextLinkRequest.from_dict(source)

    def test_context_link_rejects_private_or_path_shaped_ids(self) -> None:
        source = _read_json(CONTEXT_LINK_FIXTURE / "context-link-input.json")
        source["measurement_records"][1]["context_links"][0]["link_id"] = "/Users/lab/private/link"

        with self.assertRaisesRegex(ValueError, "context link id must be public-safe"):
            build_measurement_context_link_summary(source)

    def test_context_link_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(CONTEXT_LINK_FIXTURE / "context-link-input.json")
        result = summarize_measurement_context_links(
            MeasurementContextLinkRequest.from_dict(source)
        )
        summary = result.to_dict()

        source["context_records"][0]["declared_summary"]["trusted_entry_count"] = 99
        summary["linked_context_refs"][0]["context_id"] = "mutated"

        self.assertEqual(
            result.to_dict()["context_records"][0]["declared_summary"]["trusted_entry_count"],
            4,
        )
        self.assertEqual(result.linked_context_refs[0]["context_id"], "param-state-0007")

    def test_supporting_evidence_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        request = SupportingEvidenceReferenceRequest.from_dict(source)
        result = summarize_supporting_evidence_reference(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(
                SUPPORTING_EVIDENCE_FIXTURE / "expected-supporting-evidence-summary.json"
            ),
        )
        self.assertEqual(result.classification, "needs_related_target_review")
        self.assertEqual(result.supporting_links[0]["target_type"], "running_measurement")
        self.assertEqual(
            build_supporting_evidence_reference_summary(source),
            result.to_dict(),
        )

    def test_supporting_evidence_rejects_payload_or_file_claims(self) -> None:
        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        source["supporting_evidence_policy"]["payload_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_supporting_evidence_reference_summary(source)

        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        source["supporting_evidence_policy"]["file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "file_observation"):
            build_supporting_evidence_reference_summary(source)

    def test_supporting_evidence_rejects_private_or_path_shaped_ids(self) -> None:
        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        source["evidence"]["evidence_id"] = "/Users/lab/private/evidence"

        with self.assertRaisesRegex(ValueError, "supporting evidence id must be public-safe"):
            SupportingEvidenceReferenceRequest.from_dict(source)

        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        source["related_targets"][0]["target_id"] = "../private/target"

        with self.assertRaisesRegex(
            ValueError, "supporting evidence target id must be public-safe"
        ):
            build_supporting_evidence_reference_summary(source)

    def test_supporting_evidence_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(SUPPORTING_EVIDENCE_FIXTURE / "supporting-evidence-input.json")
        result = summarize_supporting_evidence_reference(
            SupportingEvidenceReferenceRequest.from_dict(source)
        )
        summary = result.to_dict()

        source["evidence"]["declared_reference"]["value"] = "mutated"
        summary["supporting_links"][0]["target_id"] = "mutated"

        self.assertEqual(
            result.to_dict()["evidence"]["declared_reference"]["value"],
            "artifacts/rabi-run-stderr-excerpt.txt",
        )
        self.assertEqual(result.supporting_links[0]["target_id"], "running-measurement-rabi-0042")


if __name__ == "__main__":
    unittest.main()
