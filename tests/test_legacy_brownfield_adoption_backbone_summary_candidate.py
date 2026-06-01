from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_brownfield_adoption_backbone import (
    build_legacy_brownfield_adoption_backbone_summary,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))["candidate_summary"]


def _load_input() -> dict:
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


class LegacyBrownfieldAdoptionBackboneSummaryCandidateTest(unittest.TestCase):
    def test_builds_post_run_first_backbone(self) -> None:
        summary = build_legacy_brownfield_adoption_backbone_summary(_load_input())

        self.assertEqual(
            summary["classification"],
            "legacy_brownfield_adoption_ready_for_review_evidence_readback",
        )
        self.assertEqual(summary["measurement_id"], "legacy-sidecar-measurement-0001")
        self.assertEqual(summary["stage_count"], 6)
        self.assertTrue(summary["adoption_mode"]["during_run_compatible"])
        self.assertEqual(summary["review_finding_count"], 0)
        self.assertEqual(summary["receipt_readback"]["observed_receipt_count"], 1)
        self.assertEqual(summary["effects"]["new_storage_mutation"], "not_performed")

    def test_lifecycle_events_are_declared_post_run_but_during_run_compatible(self) -> None:
        summary = build_legacy_brownfield_adoption_backbone_summary(_load_input())
        compatibility = summary["during_run_compatibility"]

        self.assertEqual(compatibility["current_ingestion"], "post_run_batch_declared_events")
        self.assertEqual(
            compatibility["future_compatible_ingestion"],
            "during_run_incremental_event_append",
        )
        self.assertEqual(compatibility["event_count"], 6)
        self.assertIn("legacy_run_started", compatibility["event_types"])
        self.assertEqual(compatibility["during_run_evidence_ref_count"], 1)
        self.assertEqual(compatibility["runner_control"], "not_claimed")

    def test_context_remains_optional_reference_posture(self) -> None:
        summary = build_legacy_brownfield_adoption_backbone_summary(_load_input())
        posture = summary["context_posture"]

        self.assertEqual(posture["context_ref_count"], 5)
        self.assertEqual(posture["selected_context_count"], 4)
        self.assertEqual(posture["unavailable_required_context_count"], 0)
        self.assertEqual(
            posture["context_handling"],
            "optional_reference_links_unless_declared_required",
        )
        self.assertEqual(posture["canonical_context_claim"], "not_made_by_legacy_backbone")

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adoption_backbone_policy"]["fresh_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "fresh_observation"):
            build_legacy_brownfield_adoption_backbone_summary(source)

        source = _load_input()
        source["adoption_backbone_policy"]["gui_workflow"] = "defined"

        with self.assertRaisesRegex(ValueError, "gui_workflow"):
            build_legacy_brownfield_adoption_backbone_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adoption_backbone_policy"]["live_runner_hook"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_brownfield_adoption_backbone_summary(source)

    def test_measurement_identity_must_match_across_stages(self) -> None:
        source = _load_input()
        source["legacy_evidence_receipt_read_view_summary"]["record"]["measurement_record_id"] = (
            "other-measurement"
        )

        with self.assertRaisesRegex(ValueError, "measurement_id continuity"):
            build_legacy_brownfield_adoption_backbone_summary(source)

    def test_append_request_and_receipt_readback_must_match(self) -> None:
        source = _load_input()
        source["reviewed_legacy_sidecar_evidence_append_receipt_summary"]["source_intent"][
            "request_id"
        ] = "other-intent"

        with self.assertRaisesRegex(ValueError, "request_id"):
            build_legacy_brownfield_adoption_backbone_summary(source)

        source = _load_input()
        source["legacy_evidence_receipt_read_view_summary"]["read_request"]["receipt_paths"] = [
            "records/legacy-sidecar-measurement-0001/review-evidence/other.json"
        ]

        with self.assertRaisesRegex(ValueError, "receipt path"):
            build_legacy_brownfield_adoption_backbone_summary(source)

    def test_sidecar_events_must_match_measurement(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["sidecar_events"][1]["measurement_id"] = (
            "other-measurement"
        )

        with self.assertRaisesRegex(ValueError, "sidecar event measurement_id"):
            build_legacy_brownfield_adoption_backbone_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_brownfield_adoption_backbone_summary(source)
        source["legacy_evidence_receipt_read_view_summary"]["receipt_view"]["status_counts"][
            "observed"
        ] = 99

        self.assertEqual(summary["receipt_readback"]["status_counts"], {"observed": 1})

    def test_non_ready_stage_keeps_backbone_as_review_state(self) -> None:
        source = _load_input()
        source["legacy_sidecar_post_run_review_summary"] = copy.deepcopy(
            source["legacy_sidecar_post_run_review_summary"]
        )
        source["legacy_sidecar_post_run_review_summary"]["classification"] = (
            "legacy_sidecar_post_run_needs_locator_review"
        )

        summary = build_legacy_brownfield_adoption_backbone_summary(source)

        self.assertEqual(summary["classification"], "legacy_brownfield_adoption_needs_review")
        self.assertEqual(summary["adoption_stages"][1]["state"], "needs_review")


if __name__ == "__main__":
    unittest.main()
