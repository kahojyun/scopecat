from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_brownfield_adoption_backbone import (
    build_legacy_brownfield_adoption_backbone_summary,
)
from implementation_candidates.legacy_calibration_handoff_parameter_state_bridge import (
    build_legacy_calibration_handoff_parameter_state_bridge_summary,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))["candidate_summary"]


def _legacy_backbone_input() -> dict:
    return {
        "adoption_backbone_policy": {
            "adoption_authority": "explicit_legacy_brownfield_adoption_backbone",
            "adoption_mode": "post_run_first",
            "during_run_compatibility": "declared_lifecycle_events_only",
            "execution_owner": "external_legacy_system",
            "input_source": "prior_legacy_sidecar_review_and_receipt_summaries",
            "fresh_observation": "not_performed",
            "new_storage_mutation": "not_performed",
            "primary_data_import": "not_performed",
            "legacy_payload_import": "not_performed",
            "legacy_source_parsing": "not_performed_by_scopecat",
            "reference_repair": "not_performed",
            "parameter_write_back": "not_performed",
            "measurement_validity": "not_claimed",
            "gui_workflow": "not_defined",
            "shared_workflow_schema": "not_defined",
        },
        "legacy_run_sidecar_summary": _candidate(
            "tests/fixtures/legacy_run_sidecar_manifest/basic_sidecar/"
            "expected-legacy-run-sidecar-summary.json"
        ),
        "legacy_sidecar_post_run_review_summary": _candidate(
            "tests/fixtures/legacy_sidecar_post_run_review/basic_review/"
            "expected-sidecar-post-run-review-summary.json"
        ),
        "legacy_locator_observation_review_bundle_summary": _candidate(
            "tests/fixtures/legacy_locator_observation_review_bundle/basic_bundle/"
            "expected-locator-observation-review-bundle-summary.json"
        ),
        "reviewed_legacy_sidecar_append_intent_summary": _candidate(
            "tests/fixtures/reviewed_legacy_sidecar_append_intent/basic_intent/"
            "expected-append-intent-summary.json"
        ),
        "reviewed_legacy_sidecar_evidence_append_receipt_summary": _candidate(
            "tests/fixtures/reviewed_legacy_sidecar_evidence_append_receipt/basic_receipt/"
            "expected-evidence-append-receipt-summary.json"
        ),
        "legacy_evidence_receipt_read_view_summary": _candidate(
            "tests/fixtures/legacy_evidence_receipt_read_view/basic_read/"
            "expected-evidence-receipt-read-summary.json"
        ),
    }


def _calibration_handoff_for_legacy_measurement(measurement_id: str) -> dict:
    summary = _candidate(
        "tests/fixtures/calibration_accepted_write_handoff/basic_handoff/"
        "expected-accepted-write-handoff-summary.json"
    )
    for step in summary["calibration_step_records"]:
        for link in step["observation_link_refs"]:
            link["measurement_record_id"] = measurement_id
    return summary


def _intake_for_legacy_measurement(measurement_id: str) -> dict:
    summary = _candidate(
        "tests/fixtures/calibration_parameter_state_intake/basic_intake/"
        "expected-intake-summary.json"
    )
    summary["provenance"]["measurement_record_refs"] = [measurement_id]
    for link in summary["provenance"]["observation_links"]:
        link["measurement_record_id"] = measurement_id
    return summary


def _load_input() -> dict:
    legacy = build_legacy_brownfield_adoption_backbone_summary(_legacy_backbone_input())
    measurement_id = legacy["measurement_id"]
    return {
        "bridge_policy": {
            "bridge_authority": "explicit_legacy_calibration_handoff_parameter_state_bridge",
            "legacy_adoption_input": "legacy_brownfield_adoption_backbone_summary",
            "calibration_input": "validated_calibration_accepted_write_handoff",
            "parameter_state_input": "calibration_parameter_state_intake_summary",
            "adoption_mode": "post_run_first",
            "handoff_posture": "review_debug_evidence_to_parameter_state_intake",
            "fresh_observation": "not_performed",
            "primary_data_import": "not_performed",
            "legacy_payload_import": "not_performed",
            "legacy_source_parsing": "not_performed_by_scopecat",
            "parameter_state_storage_mutation": "not_performed",
            "legacy_parameter_write_back": "not_performed",
            "hardware_write_back": "not_performed",
            "reference_repair": "not_performed",
            "measurement_validity": "not_claimed",
            "gui_workflow": "not_defined",
            "shared_workflow_schema": "not_defined",
        },
        "legacy_brownfield_adoption_summary": legacy,
        "calibration_accepted_write_handoff_summary": _calibration_handoff_for_legacy_measurement(
            measurement_id
        ),
        "calibration_parameter_state_intake_summary": _intake_for_legacy_measurement(
            measurement_id
        ),
        "bridge": {
            "bridge_id": "legacy-calibration-handoff-bridge-0001",
            "measurement_id": measurement_id,
            "legacy_adoption_measurement_id": measurement_id,
            "calibration_handoff_id": "handoff-rabi-qA-pi-amp-0001",
            "parameter_state_intake_review_id": (
                "parameter-state-review-from-calibration-rabi-qA-0001"
            ),
            "link_authority": "operator_declared",
            "link_posture": "review_debug_evidence_to_parameter_state_intake",
            "operator_approval": {
                "approval_state": "approved",
                "operator_role": "local_reviewer",
                "approved_at": "2026-03-01T10:08:00Z",
                "rationale": "Carry reviewed legacy calibration handoff into managed parameter-state intake.",
            },
        },
    }


class LegacyCalibrationHandoffParameterStateBridgeSummaryCandidateTest(unittest.TestCase):
    def test_builds_ready_bridge_from_legacy_sidecar_to_parameter_state_intake(self) -> None:
        summary = build_legacy_calibration_handoff_parameter_state_bridge_summary(_load_input())

        self.assertEqual(summary["classification"], "legacy_calibration_handoff_bridge_ready")
        self.assertEqual(summary["measurement_id"], "legacy-sidecar-measurement-0001")
        self.assertEqual(summary["bridge"]["handoff_apply_state"], "not_applied")
        self.assertEqual(summary["parameter_state"]["state_id"], "param-state-0008")
        self.assertEqual(summary["parameter_state"]["changed_entry_paths"], ["qubits.qA.pi_amp"])
        self.assertEqual(summary["effects"]["legacy_parameter_write_back"], "not_performed")
        self.assertEqual(summary["effects"]["parameter_state_storage_mutation"], "not_performed")

    def test_evidence_posture_keeps_sidecar_evidence_separate_from_canonical_state(self) -> None:
        summary = build_legacy_calibration_handoff_parameter_state_bridge_summary(_load_input())
        posture = summary["evidence_posture"]

        self.assertEqual(posture["legacy_sidecar_role"], "review_debug_evidence")
        self.assertEqual(posture["calibration_handoff_role"], "parameter_state_intake_source")
        self.assertEqual(
            posture["managed_parameter_state_role"],
            "canonical_parameter_context_after_intake",
        )
        self.assertEqual(
            posture["legacy_snapshots_or_debug_artifacts"],
            "supporting_evidence_not_canonical_context",
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["bridge_policy"]["legacy_parameter_write_back"] = "performed"

        with self.assertRaisesRegex(ValueError, "legacy_parameter_write_back"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

        source = _load_input()
        source["bridge_policy"]["hardware_write_back"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_write_back"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["bridge_policy"]["legacy_file_writer"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

    def test_bridge_requires_matching_measurement_across_legacy_handoff_and_intake(self) -> None:
        source = _load_input()
        source["calibration_accepted_write_handoff_summary"]["calibration_step_records"][0][
            "observation_link_refs"
        ][0]["measurement_record_id"] = "other-measurement"

        with self.assertRaisesRegex(ValueError, "calibration handoff"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

        source = _load_input()
        source["calibration_parameter_state_intake_summary"]["provenance"][
            "measurement_record_refs"
        ] = ["other-measurement"]

        with self.assertRaisesRegex(ValueError, "parameter-state intake"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

    def test_bridge_requires_matching_handoff_and_intake_review(self) -> None:
        source = _load_input()
        source["bridge"]["calibration_handoff_id"] = "other-handoff"

        with self.assertRaisesRegex(ValueError, "calibration_handoff_id"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

        source = _load_input()
        source["bridge"]["parameter_state_intake_review_id"] = "other-review"

        with self.assertRaisesRegex(ValueError, "intake review"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

    def test_bridge_requires_explicit_operator_approval(self) -> None:
        source = _load_input()
        source["bridge"]["operator_approval"]["approval_state"] = "deferred"

        with self.assertRaisesRegex(ValueError, "approved"):
            build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

    def test_not_ready_legacy_adoption_remains_review_state(self) -> None:
        source = _load_input()
        source["legacy_brownfield_adoption_summary"] = copy.deepcopy(
            source["legacy_brownfield_adoption_summary"]
        )
        source["legacy_brownfield_adoption_summary"]["classification"] = (
            "legacy_brownfield_adoption_needs_review"
        )

        summary = build_legacy_calibration_handoff_parameter_state_bridge_summary(source)

        self.assertEqual(
            summary["classification"], "legacy_calibration_handoff_bridge_needs_legacy_review"
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_calibration_handoff_parameter_state_bridge_summary(source)
        source["legacy_brownfield_adoption_summary"]["adoption_mode"]["primary_mode"] = "mutated"

        self.assertEqual(
            summary["legacy_adoption"]["adoption_mode"]["primary_mode"], "post_run_first"
        )


if __name__ == "__main__":
    unittest.main()
