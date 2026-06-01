from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_run_sidecar_manifest import (
    build_legacy_run_sidecar_manifest_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_run_sidecar_manifest" / "basic_sidecar"


def _load_input() -> dict:
    return json.loads((FIXTURE / "legacy-run-sidecar-input.json").read_text(encoding="utf-8"))


class LegacyRunSidecarManifestSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_legacy_run_sidecar_manifest_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-legacy-run-sidecar-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)

    def test_wraps_legacy_runtime_without_claiming_runner_ownership(self) -> None:
        summary = build_legacy_run_sidecar_manifest_summary(_load_input())
        runtime = summary["legacy_runtime"]
        measurement = summary["measurement_record"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(runtime["execution_owner"], "external_legacy_system")
        self.assertEqual(runtime["sidecar_mode"], "observe_declared_boundary")
        self.assertEqual(measurement["legacy_source_system_kind"], "external_legacy_system")
        self.assertEqual(
            {locator["kind"] for locator in measurement["legacy_source_locators"]},
            {"legacy_record_id", "legacy_path"},
        )
        self.assertEqual(
            attention["legacy_runtime_external"]["does_not_claim"],
            "runner_or_hardware_authority",
        )
        self.assertEqual(summary["sidecar_policy"]["hardware_control"], "not_performed")

    def test_context_is_optional_and_reference_only_by_default(self) -> None:
        summary = build_legacy_run_sidecar_manifest_summary(_load_input())
        refs = {ref["family"]: ref for ref in summary["run_start_context_refs"]}

        self.assertEqual(summary["run_start_context"]["context_ref_count"], 5)
        self.assertEqual(summary["run_start_context"]["selected_context_count"], 4)
        self.assertEqual(refs["declared_environment"]["include_state"], "unavailable")
        self.assertFalse(refs["declared_environment"]["required"])
        self.assertEqual(summary["manifest_findings"], [])

    def test_required_missing_context_is_review_finding_not_run_blocker(self) -> None:
        source = _load_input()
        source["run_start_context_refs"][-1]["required"] = True

        summary = build_legacy_run_sidecar_manifest_summary(source)
        finding = summary["manifest_findings"][0]

        self.assertEqual(
            summary["measurement_record"]["classification"], "legacy_sidecar_context_review_needed"
        )
        self.assertEqual(finding["code"], "required_run_start_context_unavailable")
        self.assertEqual(finding["family"], "declared_environment")
        self.assertEqual(finding["does_not_claim"], "legacy_run_blocked_or_invalid")
        self.assertIn(
            "required_context_unavailable",
            [item["code"] for item in summary["attention"]],
        )

    def test_partial_legacy_run_remains_reviewable_without_root_cause_claim(self) -> None:
        source = _load_input()
        source["sidecar_events"][-1] = {
            "event_id": "sidecar-evt-006",
            "event_type": "legacy_run_stopped_partial",
            "occurred_at": "2026-03-01T10:01:30Z",
            "measurement_id": "legacy-sidecar-measurement-0001",
            "final_recorded_points": 20,
            "reason": "Operator stopped the legacy sweep after the first scan block.",
        }

        summary = build_legacy_run_sidecar_manifest_summary(source)
        finding = summary["manifest_findings"][0]

        self.assertEqual(summary["measurement_record"]["lifecycle"]["state"], "partial")
        self.assertEqual(
            summary["measurement_record"]["classification"],
            "legacy_sidecar_partial_run_needs_review",
        )
        self.assertEqual(finding["code"], "legacy_run_partial")
        self.assertEqual(finding["does_not_claim"], "hardware_failure_or_measurement_invalid")

    def test_unavailable_primary_reference_is_review_finding(self) -> None:
        source = _load_input()
        source["primary_data_refs"][0].pop("legacy_source_locators")
        source["primary_data_refs"][0]["reference_state"] = "unavailable"
        source["primary_data_refs"][0]["reason"] = "Legacy data file was not declared yet."

        summary = build_legacy_run_sidecar_manifest_summary(source)
        finding = summary["manifest_findings"][0]

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "legacy_sidecar_primary_reference_review_needed",
        )
        self.assertEqual(finding["code"], "primary_data_reference_unavailable")
        self.assertEqual(finding["does_not_claim"], "primary_data_missing_from_legacy_system")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["sidecar_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["sidecar_policy"]["live_runner_proxy"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_run_sidecar_manifest_summary(source)

        source["legacy_runtime"]["entrypoint"]["display"] = "mutated"
        source["primary_data_refs"][0]["legacy_source_locators"][0]["display"] = "mutated"
        source["sidecar_events"][4]["points_recorded"] = 99

        self.assertEqual(
            summary["legacy_runtime"]["entrypoint"]["display"],
            "legacy_workspace/experiment_runner.py::run_measurement",
        )
        self.assertEqual(
            summary["primary_data_refs"][0]["legacy_source_locators"][0]["display"],
            "<redacted-legacy-storage-root>/session-0001/record-0001 - measurement.csv",
        )
        self.assertEqual(summary["sidecar_events"][4]["points_recorded"], 20)

    def test_duplicate_context_family_role_is_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["run_start_context_refs"][0])
        source["run_start_context_refs"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context family role"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_duplicate_primary_data_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["primary_data_refs"][0])
        source["primary_data_refs"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate data_id"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_legacy_locator_display_must_be_public_safe(self) -> None:
        source = _load_input()
        source["primary_data_refs"][0]["legacy_source_locators"][0]["display"] = (
            "/private/legacy.csv"
        )

        with self.assertRaisesRegex(ValueError, "locator display"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_path_locators_must_be_redacted_without_being_the_only_locator_kind(self) -> None:
        source = _load_input()
        source["primary_data_refs"][0]["legacy_source_locators"][0]["redacted"] = False

        with self.assertRaisesRegex(ValueError, "legacy_path locator"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_evidence_must_target_same_measurement(self) -> None:
        source = _load_input()
        source["supporting_evidence_refs"][0]["target"]["target_id"] = "another-run"

        with self.assertRaisesRegex(ValueError, "target this measurement"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_events_must_be_monotonic_and_match_recorded_total(self) -> None:
        source = _load_input()
        source["sidecar_events"][4]["occurred_at"] = "2026-03-01T09:59:00Z"

        with self.assertRaisesRegex(ValueError, "timestamps"):
            build_legacy_run_sidecar_manifest_summary(source)

        source = _load_input()
        source["sidecar_events"][-1]["final_recorded_points"] = 19

        with self.assertRaisesRegex(ValueError, "final recorded points"):
            build_legacy_run_sidecar_manifest_summary(source)

    def test_boundary_output_keeps_import_storage_and_execution_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-legacy-run-sidecar-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("not storage mutation", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["sidecar_policy"]["legacy_import_acceptance"], "not_performed")
        self.assertEqual(candidate["sidecar_policy"]["parameter_write_back"], "not_performed")
        self.assertEqual(
            attention["primary_data_not_observed"]["does_not_claim"],
            "primary_data_opened_or_validated",
        )
        self.assertIn("hardware-control", " ".join(expected["decisions_not_earned"]))


if __name__ == "__main__":
    unittest.main()
