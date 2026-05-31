from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.running_record_supporting_evidence_update import (
    build_running_record_supporting_evidence_update_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "running_record_supporting_evidence_update" / "basic_update"


def _load_input() -> dict:
    return json.loads((FIXTURE / "update-input.json").read_text(encoding="utf-8"))


class RunningRecordSupportingEvidenceUpdateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_running_record_supporting_evidence_update_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-update-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_during_run_evidence_is_not_run_start_context(self) -> None:
        summary = build_running_record_supporting_evidence_update_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["evidence_lifecycle_counts"], {"during_run": 1})
        self.assertEqual(
            attention["during_run_evidence_only"]["does_not_claim"],
            "run_start_context_requirement",
        )

    def test_evidence_update_is_not_durable_record_write_or_runner_control(self) -> None:
        summary = build_running_record_supporting_evidence_update_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["evidence_update_policy"]["record_write"], "not_performed")
        self.assertEqual(summary["evidence_update_policy"]["runner_control"], "not_performed")
        self.assertEqual(
            attention["record_write_not_performed"]["does_not_claim"],
            "durable_record_update",
        )
        self.assertEqual(
            attention["runner_not_owned"]["does_not_claim"],
            "runner_or_log_streaming_authority",
        )

    def test_supporting_evidence_findings_are_review_not_validity_claims(self) -> None:
        summary = build_running_record_supporting_evidence_update_summary(_load_input())
        finding = summary["evidence_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["classification"], "running_record_evidence_update_needs_review")
        self.assertEqual(finding["finding"], "related_target_unavailable")
        self.assertEqual(finding["does_not_claim"], "measurement_or_context_invalid")
        self.assertEqual(
            attention["supporting_evidence_findings_present"]["does_not_claim"],
            "measurement_invalid",
        )

    def test_ready_classification_when_supporting_evidence_has_no_findings(self) -> None:
        source = _load_input()
        evidence_summary = source["supporting_evidence_summaries"][0]
        evidence_summary["reference_findings"] = []
        evidence_summary["classification"] = "ready_for_supporting_evidence_review"
        evidence_summary["supporting_links"][2]["target_state"] = "resolved"
        evidence_summary["supporting_links"][2]["reason"] = None

        summary = build_running_record_supporting_evidence_update_summary(source)

        self.assertEqual(
            summary["classification"],
            "running_record_evidence_update_ready_for_review",
        )
        self.assertEqual(summary["evidence_findings"], [])
        self.assertNotIn(
            "supporting_evidence_findings_present",
            {item["code"] for item in summary["attention"]},
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_running_record_supporting_evidence_update_summary(source)

        source["running_record"]["label"] = "mutated"
        source["supporting_evidence_summaries"][0]["evidence"]["declared_reference"]["value"] = (
            "mutated"
        )

        self.assertEqual(summary["running_record"]["label"], "Running Rabi measurement")
        self.assertEqual(
            summary["evidence_refs"][0]["declared_reference"]["value"],
            "artifacts/rabi-run-stderr-excerpt.txt",
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_update_policy"]["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            build_running_record_supporting_evidence_update_summary(source)

        source = _load_input()
        source["evidence_update_policy"]["runner_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "runner_control"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_update_policy"]["live_log_tail"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_running_record_shape_and_state_are_validated(self) -> None:
        source = _load_input()
        source["running_record"]["storage_path"] = "records/running"

        with self.assertRaisesRegex(ValueError, "running record"):
            build_running_record_supporting_evidence_update_summary(source)

        source = _load_input()
        source["running_record"]["lifecycle_state"] = "complete"

        with self.assertRaisesRegex(ValueError, "lifecycle_state"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_supporting_evidence_must_be_during_run(self) -> None:
        source = _load_input()
        source["supporting_evidence_summaries"][0]["evidence"]["lifecycle_stage"] = (
            "post_run_review"
        )

        with self.assertRaisesRegex(ValueError, "lifecycle_stage"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_supporting_evidence_must_link_to_running_record(self) -> None:
        source = _load_input()
        source["supporting_evidence_summaries"][0]["supporting_links"][0]["target_id"] = (
            "other-running-measurement"
        )

        with self.assertRaisesRegex(ValueError, "link to the running measurement"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_running_measurement_link_must_be_resolved(self) -> None:
        source = _load_input()
        source["supporting_evidence_summaries"][0]["supporting_links"][0]["target_state"] = (
            "unavailable"
        )

        with self.assertRaisesRegex(ValueError, "must be resolved"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_duplicate_evidence_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["supporting_evidence_summaries"][0])
        source["supporting_evidence_summaries"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate evidence_id"):
            build_running_record_supporting_evidence_update_summary(source)

    def test_supporting_evidence_policy_boundaries_are_enforced(self) -> None:
        source = _load_input()
        policy = source["supporting_evidence_summaries"][0]["supporting_evidence_policy"]
        policy["payload_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_running_record_supporting_evidence_update_summary(source)

        source = _load_input()
        policy = source["supporting_evidence_summaries"][0]["supporting_evidence_policy"]
        policy["artifact_provenance"] = "validated"

        with self.assertRaisesRegex(ValueError, "artifact_provenance"):
            build_running_record_supporting_evidence_update_summary(source)


if __name__ == "__main__":
    unittest.main()
