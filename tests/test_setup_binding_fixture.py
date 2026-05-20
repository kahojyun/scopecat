from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "setup_binding" / "basic_binding_context"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "setup-binding-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-setup-binding-summary.json").read_text(encoding="utf-8")
    )


class SetupBindingFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "setup-binding-input.json",
            FIXTURE / "expected-setup-binding-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_measurement_context_uses_named_input_snapshot_list(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        source_inputs = source["measurements"][0]["inputs"]
        inputs = summary["measurement_references"][0]["inputs"]

        self.assertEqual(inputs, source_inputs)
        self.assertEqual(
            [entry["name"] for entry in inputs],
            ["parameter_state", "setup_binding", "station_registry"],
        )
        self.assertEqual(
            summary["input_snapshot_families"][0]["lifecycle_semantics"],
            "parameter_lineage_and_review",
        )
        self.assertEqual(
            summary["input_snapshot_families"][1]["lifecycle_semantics"],
            "binding_snapshot_and_diff",
        )

    def test_station_registry_is_separate_redacted_context(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        registry = summary["station_registry_contexts"][0]

        self.assertEqual(registry["registry_id"], "station-registry-mmcs2-redacted")
        self.assertEqual(registry["registry_scope"], "station_configuration")
        self.assertFalse(registry["contains_connection_payloads"])
        self.assertEqual(
            registry["resource_count"],
            len(source["station_registry_contexts"][0]["resource_labels"]),
        )

    def test_selected_binding_carries_logical_bindings_and_generated_views(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        selected_source = {
            item["snapshot_id"]: item for item in source["setup_binding_snapshots"]
        }["setup-binding-0002"]
        selected_summary = {
            item["snapshot_id"]: item for item in summary["setup_bindings"]
        }["setup-binding-0002"]

        self.assertEqual(selected_summary["role"], "selected_binding_snapshot")
        self.assertEqual(
            selected_summary["logical_binding_count"],
            len(selected_source["logical_bindings"]),
        )
        self.assertEqual(
            selected_summary["generated_view_count"],
            len(selected_source["generated_views"]),
        )
        self.assertEqual(
            {view["view_kind"] for view in summary["generated_views"]},
            {"line_info", "readout_group"},
        )
        self.assertEqual(
            {view["consumer_hint"] for view in summary["generated_views"]},
            {"runtime_line_selection", "readout_position_selection"},
        )

    def test_binding_diff_is_attention_not_parameter_invalidation(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()["candidate_summary"]
        diff = summary["binding_diffs"][0]
        attention = summary["attention"][0]

        self.assertEqual(diff["diff_counts"], {"changed": 1, "added": 1, "removed": 0})
        self.assertEqual(
            [entry["role"] for entry in diff["diff_entries"]],
            ["z_line", "z_line"],
        )
        self.assertEqual(
            [entry["logical_entity"] for entry in diff["diff_entries"]],
            ["qA", "cAB"],
        )
        self.assertEqual(source["attention_expected"], [attention["code"]])
        self.assertEqual(attention["does_not_claim"], "parameter_state_invalid")

    def test_fixture_boundary_does_not_execute_project_generators(self) -> None:
        source = _input_fixture()
        summary = _expected_summary()
        selected = {
            item["snapshot_id"]: item for item in source["setup_binding_snapshots"]
        }["setup-binding-0002"]
        generator = selected["source_artifacts"][1]

        self.assertEqual(generator["execution_claim"], "not_executed_by_fixture")
        self.assertIn("generator or converter execution", summary["decisions_not_earned"])
        self.assertIn(
            "black-box provenance",
            summary["reference_semantics"]["generated_views"],
        )

    def test_review_markdown_states_fixture_boundary(self) -> None:
        review = (FIXTURE / "expected-setup-binding-review.md").read_text(encoding="utf-8")

        self.assertIn("Measurement Inputs", review)
        self.assertIn("parameter_state", review)
        self.assertIn("setup_binding", review)
        self.assertIn("station_registry", review)
        self.assertIn("Generated Views", review)
        self.assertIn("black-box provenance", review)
        self.assertIn("does not claim that the selected parameter", review)
        self.assertIn("claim current hardware state", review)


if __name__ == "__main__":
    unittest.main()
