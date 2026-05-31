from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "context_inclusion_semantics" / "basic_semantics"


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-context-inclusion-summary.json").read_text(encoding="utf-8")
    )


class ContextInclusionSemanticsFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "context-inclusion-input.json",
            FIXTURE / "expected-context-inclusion-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_semantics_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn(
            "required controls absence", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(
            candidate["context_inclusion_policy"]["selected_context_recording"],
            "record_when_context_id_is_provided",
        )
        self.assertEqual(
            candidate["context_inclusion_policy"]["required_semantics"],
            "absence_severity_only",
        )
        self.assertIn("template language", expected["decisions_not_earned"])

    def test_selected_optional_contexts_are_recorded(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        optional_selected = [
            ref
            for ref in candidate["context_refs"]
            if ref["include_state"] == "selected" and not ref["required"]
        ]

        self.assertEqual(
            [ref["family"] for ref in optional_selected],
            ["setup_binding", "managed_code_version"],
        )
        self.assertEqual({ref["recording_state"] for ref in optional_selected}, {"recorded"})
        self.assertEqual(candidate["prepared_contexts"][0]["recorded_optional_context_count"], 2)

    def test_optional_absence_is_not_required_finding(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(len(candidate["optional_absence_notes"]), 2)
        self.assertEqual(len(candidate["required_absence_findings"]), 1)
        self.assertEqual(
            candidate["required_absence_findings"][0]["family"],
            "measurement_intent",
        )


if __name__ == "__main__":
    unittest.main()
