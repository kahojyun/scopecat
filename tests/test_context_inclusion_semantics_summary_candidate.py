from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.context_inclusion_semantics import (
    build_context_inclusion_semantics_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "context_inclusion_semantics" / "basic_semantics"


def _load_input() -> dict:
    return json.loads((FIXTURE / "context-inclusion-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads(
        (FIXTURE / "expected-context-inclusion-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


def _context_ref(source: dict, family: str) -> dict:
    for context_ref in source["prepared_contexts"][0]["context_refs"]:
        if context_ref["family"] == family:
            return context_ref
    raise AssertionError(f"fixture missing context ref family={family}")


class ContextInclusionSemanticsSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_context_inclusion_semantics_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_context_inclusion_semantics_summary(source)

        source["context_records"][0]["declared_summary"]["trusted_entry_count"] = 99
        source["prepared_contexts"][0]["context_refs"][1]["context_id"] = "mutated"

        self.assertEqual(
            summary["context_records"][0]["declared_summary"]["trusted_entry_count"], 2
        )
        self.assertEqual(
            summary["context_refs"][1]["context_id"],
            "setup-binding-opportunistic-0001",
        )

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["context_inclusion_policy"]["template_language"] = "defined"

        with self.assertRaisesRegex(ValueError, "template_language"):
            build_context_inclusion_semantics_summary(source)

    def test_selected_optional_context_with_id_is_recorded(self) -> None:
        source = _load_input()
        setup_ref = _context_ref(source, "setup_binding")
        self.assertFalse(setup_ref["required"])

        summary = build_context_inclusion_semantics_summary(source)
        setup_summary = [
            ref for ref in summary["context_refs"] if ref["family"] == "setup_binding"
        ][0]

        self.assertEqual(setup_summary["recording_state"], "recorded")
        self.assertEqual(setup_summary["absence_severity"], "informational")

    def test_optional_unavailable_context_is_informational(self) -> None:
        summary = build_context_inclusion_semantics_summary(_load_input())

        optional_families = {note["family"] for note in summary["optional_absence_notes"]}
        finding_families = {finding["family"] for finding in summary["required_absence_findings"]}

        self.assertIn("declared_environment", optional_families)
        self.assertNotIn("declared_environment", finding_families)

    def test_required_unavailable_context_is_review_finding(self) -> None:
        summary = build_context_inclusion_semantics_summary(_load_input())

        self.assertEqual(
            summary["required_absence_findings"][0]["finding"],
            "required_context_unavailable",
        )
        self.assertEqual(
            summary["context_refs"][-1]["absence_severity"],
            "review",
        )

    def test_opportunistic_context_cannot_be_required(self) -> None:
        source = _load_input()
        _context_ref(source, "declared_environment")["required"] = True

        with self.assertRaisesRegex(ValueError, "opportunistic"):
            build_context_inclusion_semantics_summary(source)

    def test_selected_context_must_reference_existing_record(self) -> None:
        source = _load_input()
        _context_ref(source, "managed_code_version")["context_id"] = "missing-context"

        with self.assertRaisesRegex(ValueError, "missing selected context"):
            build_context_inclusion_semantics_summary(source)

    def test_optional_not_selected_must_not_be_required(self) -> None:
        source = _load_input()
        _context_ref(source, "station_registry")["required"] = True
        _context_ref(source, "station_registry")["requirement_source"] = "declared_template_input"

        with self.assertRaisesRegex(ValueError, "optional_not_selected"):
            build_context_inclusion_semantics_summary(source)


if __name__ == "__main__":
    unittest.main()
