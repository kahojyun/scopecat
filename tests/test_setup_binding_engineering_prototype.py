from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.setup_binding import (
    SetupBindingSummaryRequest,
    build_setup_binding_summary,
    summarize_setup_binding_context,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "setup_binding" / "basic_binding_context"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


class SetupBindingEngineeringPrototypeTest(unittest.TestCase):
    def test_typed_api_matches_validated_candidate_output(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        request = SetupBindingSummaryRequest.from_dict(source)
        result = summarize_setup_binding_context(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(FIXTURE / "expected-setup-binding-summary.json"),
        )
        self.assertEqual(result.setup_bindings[1]["role"], "selected_binding_snapshot")
        self.assertEqual(build_setup_binding_summary(source), result.to_dict())

    def test_rejects_station_registry_connection_payloads(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        source["station_registry_contexts"][0]["contains_connection_payloads"] = True

        with self.assertRaisesRegex(ValueError, "connection payloads must remain redacted"):
            build_setup_binding_summary(source)

    def test_rejects_generator_execution_claims(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        source["setup_binding_snapshots"][1]["source_artifacts"][1]["execution_claim"] = (
            "executed_by_scopecat"
        )

        with self.assertRaisesRegex(ValueError, "must not claim execution"):
            build_setup_binding_summary(source)

    def test_rejects_hardware_state_claims(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        source["measurements"][0]["hardware_state_claim"] = "verified_current_state"

        with self.assertRaisesRegex(ValueError, "hardware state must remain not_recorded"):
            SetupBindingSummaryRequest.from_dict(source)

    def test_rejects_missing_required_run_start_input(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        source["measurements"][0]["inputs"] = [
            item for item in source["measurements"][0]["inputs"] if item["name"] != "setup_binding"
        ]

        with self.assertRaisesRegex(ValueError, "missing required input family"):
            build_setup_binding_summary(source)

    def test_rejects_private_or_path_shaped_ids(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        source["setup_binding_snapshots"][0]["sample_id"] = "/Users/lab/private/sample"

        with self.assertRaisesRegex(ValueError, "setup binding sample id must be public-safe"):
            build_setup_binding_summary(source)

    def test_outputs_do_not_alias_inputs_or_result_objects(self) -> None:
        source = _read_json(FIXTURE / "setup-binding-input.json")
        original = copy.deepcopy(source)
        result = summarize_setup_binding_context(SetupBindingSummaryRequest.from_dict(source))
        summary = result.to_dict()

        source["setup_binding_snapshots"][1]["snapshot_label"] = "mutated"
        summary["setup_bindings"][1]["snapshot_label"] = "mutated"

        self.assertEqual(
            result.setup_bindings[1]["snapshot_label"],
            "qA default binding after bias-line move",
        )
        self.assertNotEqual(source, original)


if __name__ == "__main__":
    unittest.main()
