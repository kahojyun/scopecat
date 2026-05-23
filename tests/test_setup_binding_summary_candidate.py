from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.setup_binding import build_setup_binding_summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "setup_binding" / "basic_binding_context"


def _load_input() -> dict:
    return json.loads((FIXTURE / "setup-binding-input.json").read_text(encoding="utf-8"))


class SetupBindingSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_setup_binding_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-setup-binding-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)

    def test_summarizes_selected_binding_without_absorbing_payload(self) -> None:
        summary = build_setup_binding_summary(_load_input())
        selected = {item["snapshot_id"]: item for item in summary["setup_bindings"]}[
            "setup-binding-0002"
        ]

        self.assertEqual(selected["role"], "selected_binding_snapshot")
        self.assertEqual(
            selected["inner_payload_handling"],
            "opaque_payload_with_declared_summary_fields",
        )
        self.assertEqual(selected["logical_binding_count"], 6)
        self.assertEqual(selected["generated_view_count"], 2)
        self.assertNotIn("source_artifacts", selected)

    def test_generated_views_are_declared_context_not_generator_execution(self) -> None:
        summary = build_setup_binding_summary(_load_input())
        views = {view["view_kind"]: view for view in summary["generated_views"]}

        self.assertEqual(set(views), {"line_info", "readout_group"})
        self.assertEqual(views["line_info"]["consumer_hint"], "runtime_line_selection")
        self.assertEqual(views["readout_group"]["entry_count"], 1)

    def test_binding_change_is_attention_not_parameter_invalidation(self) -> None:
        summary = build_setup_binding_summary(_load_input())
        attention = summary["attention"][0]

        self.assertEqual(attention["code"], "binding_changed_since_prior_calibration")
        self.assertEqual(attention["severity"], "review")
        self.assertEqual(attention["does_not_claim"], "parameter_state_invalid")

    def test_duplicate_setup_binding_ids_are_rejected(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"].append(
            copy.deepcopy(source["setup_binding_snapshots"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            build_setup_binding_summary(source)

    def test_setup_binding_must_reference_known_station_registry(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"][0]["selected_registry_id"] = "missing-registry"

        with self.assertRaisesRegex(ValueError, "missing station registry"):
            build_setup_binding_summary(source)

    def test_binding_resource_must_reference_known_registry_resource(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"][0]["logical_bindings"][0]["registry_resource_id"] = (
            "missing-resource"
        )

        with self.assertRaisesRegex(ValueError, "missing registry resource"):
            build_setup_binding_summary(source)

    def test_generator_references_must_not_claim_execution(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"][1]["source_artifacts"][1]["execution_claim"] = (
            "executed_by_candidate"
        )

        with self.assertRaisesRegex(ValueError, "must not claim execution"):
            build_setup_binding_summary(source)

    def test_measurement_runtime_context_refs_must_be_known_generated_views(self) -> None:
        source = _load_input()
        source["measurements"][0]["runtime_context_refs"].append("missing-view")

        with self.assertRaisesRegex(ValueError, "missing generated view"):
            build_setup_binding_summary(source)

    def test_runtime_context_refs_must_belong_to_selected_setup_binding(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"][0]["generated_views"].append(
            {
                "view_id": "line-info-prior-0001",
                "view_kind": "line_info",
                "source_relation": "generated_from_binding_and_parameter_context",
                "consumer_hint": "runtime_line_selection",
                "entries": [],
            }
        )
        source["measurements"][0]["runtime_context_refs"].append("line-info-prior-0001")

        with self.assertRaisesRegex(ValueError, "selected setup binding"):
            build_setup_binding_summary(source)

    def test_measurement_requires_boundary_input_families(self) -> None:
        source = _load_input()
        source["measurements"][0]["inputs"] = [
            item for item in source["measurements"][0]["inputs"] if item["name"] != "setup_binding"
        ]

        with self.assertRaisesRegex(ValueError, "missing required input family: setup_binding"):
            build_setup_binding_summary(source)

    def test_measurement_station_registry_must_match_selected_binding(self) -> None:
        source = _load_input()
        source["station_registry_contexts"].append(
            {
                "registry_id": "station-registry-other-redacted",
                "registry_label": "other redacted station registry",
                "registry_scope": "station_configuration",
                "authority": "fixture_declared_summary",
                "contains_connection_payloads": False,
                "resource_labels": [],
            }
        )
        source["measurements"][0]["inputs"][2]["snapshot_id"] = "station-registry-other-redacted"

        with self.assertRaisesRegex(ValueError, "station registry input must match"):
            build_setup_binding_summary(source)

    def test_parameter_state_family_must_match_collection(self) -> None:
        source = _load_input()
        source["parameter_state_summaries"][0]["snapshot_family"] = "setup_binding"

        with self.assertRaisesRegex(ValueError, "parameter state snapshot_family"):
            build_setup_binding_summary(source)

    def test_setup_binding_family_must_match_collection(self) -> None:
        source = _load_input()
        source["setup_binding_snapshots"][0]["snapshot_family"] = "parameter_state"

        with self.assertRaisesRegex(ValueError, "setup binding snapshot_family"):
            build_setup_binding_summary(source)

    def test_binding_diff_entries_must_match_snapshot_values(self) -> None:
        source = _load_input()
        source["binding_diffs"][0]["diff_entries"][0]["old_physical_resource_label"] = (
            "wrong_old_label"
        )

        with self.assertRaisesRegex(ValueError, "old value does not match"):
            build_setup_binding_summary(source)

    def test_added_binding_diff_must_be_absent_from_prior_snapshot(self) -> None:
        source = _load_input()
        source["binding_diffs"][0]["diff_entries"][1]["logical_entity"] = "qA"

        with self.assertRaisesRegex(ValueError, "must be absent"):
            build_setup_binding_summary(source)

    def test_measurement_must_not_claim_hardware_state(self) -> None:
        source = _load_input()
        source["measurements"][0]["hardware_state_claim"] = "current_state_verified"

        with self.assertRaisesRegex(ValueError, "hardware state"):
            build_setup_binding_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_setup_binding_summary(source)

        source["measurements"][0]["logical_targets"].append("mutated")
        source["measurements"][0]["inputs"][0]["snapshot_id"] = "mutated"
        source["measurements"][0]["runtime_context_refs"][0] = "mutated"

        measurement = summary["measurement_references"][0]
        self.assertEqual(measurement["logical_targets"], ["qA", "cAB"])
        self.assertEqual(measurement["inputs"][0]["snapshot_id"], "param-state-0002")
        self.assertEqual(measurement["runtime_context_refs"][0], "line-info-qA-0002")


if __name__ == "__main__":
    unittest.main()
