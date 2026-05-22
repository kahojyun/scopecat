from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.experiment_code_selection import (
    build_experiment_code_selection_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "experiment_code_selection" / "messy_external_capture"


def _load_input() -> dict:
    return json.loads((FIXTURE / "code-selection-input.json").read_text(encoding="utf-8"))


class ExperimentCodeSelectionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_experiment_code_selection_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-code-selection-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_selected_context_summarizes_entrypoint_without_reading_code(self) -> None:
        summary = build_experiment_code_selection_summary(_load_input())
        context = summary["selected_code_contexts"][0]

        self.assertEqual(context["entrypoint_path"], "readout_calibration_entrypoint.ipynb")
        self.assertEqual(context["entrypoint_recorded_form"], "source_without_outputs")
        self.assertEqual(context["execution_claim"], "not_executed_by_fixture")
        self.assertEqual(context["mutation_capability"], "not_analyzed")

    def test_attention_is_derived_from_boundary_policy(self) -> None:
        source = _load_input()
        source["capture_policy"]["internal_git_inspection"] = "performed_elsewhere"
        source["selected_code_contexts"][0]["mutation_capability"]["execution_permission"] = (
            "granted_elsewhere"
        )

        summary = build_experiment_code_selection_summary(source)

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            ["notebook_outputs_stripped", "unwhitelisted_files_not_recorded"],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_experiment_code_selection_summary(source)

        source["capture_policy"]["mode"] = "mutated"
        source["selected_code_contexts"][0]["declared_context_refs"][0]["ref_id"] = "mutated"
        source["calibration_steps"][0]["inputs"][0]["snapshot_id"] = "mutated"

        self.assertEqual(summary["capture_policy"]["mode"], "minimal_whitelist_capture")
        self.assertEqual(
            summary["declared_context_refs"][0]["ref_id"],
            "env-profile-control-pc-redacted",
        )
        self.assertEqual(
            summary["calibration_step_references"][0]["inputs"][0]["snapshot_id"],
            "code-context-readout-cali-0001",
        )

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["selected_code_contexts"][0])
        source["selected_code_contexts"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_experiment_code_selection_summary(source)

    def test_context_must_reference_known_root(self) -> None:
        source = _load_input()
        source["selected_code_contexts"][0]["external_root_id"] = "missing-root"

        with self.assertRaisesRegex(ValueError, "references missing root"):
            build_experiment_code_selection_summary(source)

    def test_entrypoint_must_be_whitelisted(self) -> None:
        source = _load_input()
        source["selected_code_contexts"][0]["entrypoint"]["path"] = "not-whitelisted.ipynb"

        with self.assertRaisesRegex(ValueError, "entrypoint must be whitelisted"):
            build_experiment_code_selection_summary(source)

    def test_notebook_entrypoint_must_be_recorded_without_outputs(self) -> None:
        source = _load_input()
        source["selected_code_contexts"][0]["entrypoint"]["recorded_form"] = "with_outputs"

        with self.assertRaisesRegex(ValueError, "notebook entrypoint"):
            build_experiment_code_selection_summary(source)

    def test_calibration_step_code_context_input_must_reference_selected_context(self) -> None:
        source = _load_input()
        source["calibration_steps"][0]["inputs"][0]["snapshot_id"] = "missing-context"

        with self.assertRaisesRegex(ValueError, "missing code context"):
            build_experiment_code_selection_summary(source)

    def test_captured_version_scope_must_match_selected_context(self) -> None:
        source = _load_input()
        source["captured_version_candidates"][0]["capture_scope"]["whitelisted_files"] = [
            "readout_calibration_entrypoint.ipynb"
        ]

        with self.assertRaisesRegex(ValueError, "whitelist must match"):
            build_experiment_code_selection_summary(source)


if __name__ == "__main__":
    unittest.main()
