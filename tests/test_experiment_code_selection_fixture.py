from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "experiment_code_selection" / "messy_external_capture"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "code-selection-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-code-selection-summary.json").read_text(encoding="utf-8")
    )


class ExperimentCodeSelectionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "code-selection-input.json",
            FIXTURE / "expected-code-selection-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_git_state_is_evidence_not_product_authority(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        root = summary["candidate_summary"]["external_code_roots"][0]
        source_root = source["external_code_roots"][0]

        self.assertTrue(root["git_present"])
        self.assertEqual(root["working_tree_state"], "dirty")
        self.assertEqual(
            root["git_authority"],
            source_root["git_observation"]["authority"],
        )
        self.assertIn("Git observations", summary["reference_semantics"]["git_state"])
        self.assertNotIn("git_is_product_authority", json.dumps(root))

    def test_selected_context_keeps_entrypoint_helper_scope_and_classifications(
        self,
    ) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        context = summary["selected_code_contexts"][0]

        self.assertEqual(context["entrypoint_path"], "Braid_cali_new.ipynb")
        self.assertEqual(context["entrypoint_kind"], "notebook")
        self.assertEqual(context["execution_claim"], "not_executed_by_fixture")
        self.assertEqual(
            context["helper_root_count"],
            len(source["selected_code_contexts"][0]["included_helper_roots"]),
        )
        self.assertEqual(
            {item["classification"] for item in summary["classified_paths"]},
            {"checkpoint", "backup_variant", "cache"},
        )
        self.assertEqual(
            {item["selection_status"] for item in summary["classified_paths"]},
            {
                "excluded_by_policy",
                "visible_ambiguity_not_selected",
            },
        )

    def test_generated_companions_are_linked_without_regeneration(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        generated = summary["generated_companions"]
        source_generated = source["selected_code_contexts"][0]["generated_companions"]

        self.assertEqual(
            [item["artifact_id"] for item in generated],
            [item["artifact_id"] for item in source_generated],
        )
        self.assertEqual(
            {item["regeneration_claim"] for item in generated},
            {"not_regenerated_by_fixture"},
        )
        self.assertIn(
            "generated artifact regeneration",
            _expected_summary()["decisions_not_earned"],
        )

    def test_calibration_step_references_code_context_as_named_input(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        reference = summary["calibration_step_references"][0]

        self.assertEqual(reference["inputs"], source["calibration_steps"][0]["inputs"])
        self.assertEqual(
            [entry["name"] for entry in reference["inputs"]],
            ["code_context", "parameter_state", "setup_binding"],
        )
        self.assertEqual(
            reference["inputs"][0]["snapshot_id"],
            "code-context-readout-cali-0001",
        )

    def test_mutation_and_environment_are_attention_not_execution_permission(self) -> None:
        summary = _expected_summary()["candidate_summary"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["selected_code_contexts"][0]["mutation_capability"],
            "hardware_active_and_parameter_mutating",
        )
        self.assertIn("hardware_active_code_selected", attention)
        self.assertEqual(
            attention["hardware_active_code_selected"]["does_not_claim"],
            "execution_permission",
        )
        self.assertEqual(
            [item["hint_kind"] for item in summary["environment_hints"]],
            ["python_environment", "local_service", "hardware_stack"],
        )

    def test_captured_version_candidate_is_not_storage_or_workflow_contract(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        candidate = summary["candidate_summary"]["captured_version_candidates"][0]
        source_candidate = source["captured_version_candidates"][0]

        self.assertEqual(candidate["candidate_status"], "candidate_not_committed_contract")
        self.assertEqual(candidate["storage_claim"], "not_decided_by_fixture")
        self.assertEqual(
            candidate["included_helper_roots"],
            source_candidate["capture_scope"]["included_helper_roots"],
        )
        self.assertIn("workflow DAG", summary["decisions_not_earned"])
        self.assertIn("final managed workspace storage", summary["decisions_not_earned"])

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-code-selection-review.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Git is observed evidence only", review)
        self.assertIn("not require the user to understand branch", review)
        self.assertIn("does not regenerate", review)
        self.assertIn("does not grant execution", review)
        self.assertIn("candidate for future Scopecat-managed code", review)
        self.assertIn("workflow", review)


if __name__ == "__main__":
    unittest.main()
