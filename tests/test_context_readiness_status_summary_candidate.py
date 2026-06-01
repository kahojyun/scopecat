from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.context_readiness_status import (
    build_context_readiness_status_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "context_readiness_status" / "basic_context_status"


def _load_input() -> dict:
    return json.loads((FIXTURE / "context-status-input.json").read_text(encoding="utf-8"))


class ContextReadinessStatusSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_context_readiness_status_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-context-status-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_ready_review_and_blocked_statuses_are_distinct(self) -> None:
        summary = build_context_readiness_status_summary(_load_input())
        statuses = {item["context_id"]: item for item in summary["context_statuses"]}

        self.assertEqual(
            statuses["parameter-state-rabi-accepted-0042"]["classification"],
            "ready_for_context_review",
        )
        self.assertEqual(
            statuses["declared-environment-rabi-0042"]["classification"],
            "attention_needed_for_context_review",
        )
        self.assertEqual(
            statuses["calibration-continuation-rabi-0042"]["classification"],
            "blocked_for_context_review",
        )
        self.assertEqual(summary["overall_classification"], "blocked_for_context_review")

    def test_context_review_block_is_not_run_blocking_claim(self) -> None:
        summary = build_context_readiness_status_summary(_load_input())
        finding = summary["status_findings"][1]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(finding["finding"], "context_progress_blocked")
        self.assertEqual(finding["required_for_current_review"], True)
        self.assertEqual(finding["does_not_claim"], "run_blocking_decision")
        self.assertEqual(
            attention["context_review_block_present"]["does_not_claim"],
            "automatic_run_blocking",
        )

    def test_review_attention_does_not_claim_measurement_validity(self) -> None:
        summary = build_context_readiness_status_summary(_load_input())
        finding = summary["status_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(finding["finding"], "context_validity_unverified")
        self.assertEqual(finding["severity"], "review")
        self.assertEqual(finding["does_not_claim"], "runnable_readiness")
        self.assertEqual(
            attention["context_attention_present"]["does_not_claim"],
            "measurement_validity",
        )

    def test_ready_overall_when_all_status_facts_are_info(self) -> None:
        source = _load_input()
        source["context_records"][1]["status_facts"][0]["state"] = "valid"
        source["context_records"][1]["status_facts"][0]["severity"] = "info"
        source["context_records"][1]["status_facts"][0]["does_not_claim"] = "measurement_validity"
        source["context_records"][2]["status_facts"][0]["state"] = "complete"
        source["context_records"][2]["status_facts"][0]["severity"] = "info"
        source["context_records"][2]["status_facts"][0]["required_for_current_review"] = False
        source["context_records"][2]["status_facts"][0]["does_not_claim"] = "run_blocking_decision"

        summary = build_context_readiness_status_summary(source)

        self.assertEqual(summary["overall_classification"], "ready_for_context_review")
        self.assertEqual(summary["status_findings"], [])

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_context_readiness_status_summary(source)

        source["context_records"][0]["declared_summary"]["trusted_entry_count"] = 99
        source["context_records"][0]["status_facts"][0]["basis"] = "mutated"

        self.assertEqual(
            summary["context_statuses"][0]["declared_summary"]["trusted_entry_count"],
            4,
        )
        self.assertNotEqual(summary["status_findings"][0]["basis"], "mutated")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["context_status_policy"]["hardware_readiness_check"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_readiness_check"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_status_policy"]["run_blocking_decision"] = "claimed"

        with self.assertRaisesRegex(ValueError, "run_blocking_decision"):
            build_context_readiness_status_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["context_status_policy"]["run_start_permission"] = "granted"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_context_readiness_status_summary(source)

    def test_duplicate_context_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["context_records"][0])
        source["context_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate context_id"):
            build_context_readiness_status_summary(source)

    def test_duplicate_fact_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["context_records"][0]["status_facts"][0])
        source["context_records"][0]["status_facts"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate fact_id"):
            build_context_readiness_status_summary(source)

    def test_unsupported_family_dimension_state_and_severity_are_rejected(self) -> None:
        source = _load_input()
        source["context_records"][0]["family"] = "runtime_environment"

        with self.assertRaisesRegex(ValueError, "unsupported context family"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_records"][0]["status_facts"][0]["dimension"] = "safety"

        with self.assertRaisesRegex(ValueError, "unsupported status dimension"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_records"][0]["status_facts"][0]["state"] = "safe_to_run"

        with self.assertRaisesRegex(ValueError, "unsupported status state"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_records"][0]["status_facts"][0]["severity"] = "run_blocker"

        with self.assertRaisesRegex(ValueError, "severity"):
            build_context_readiness_status_summary(source)

    def test_required_current_review_fact_must_block_context_review(self) -> None:
        source = _load_input()
        source["context_records"][2]["status_facts"][0]["severity"] = "review"

        with self.assertRaisesRegex(ValueError, "must block context review"):
            build_context_readiness_status_summary(source)

    def test_payload_handling_and_fact_authority_are_enforced(self) -> None:
        source = _load_input()
        source["context_records"][0]["payload_handling"] = "inline_payload"

        with self.assertRaisesRegex(ValueError, "payload handling"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_records"][0]["status_facts"][0]["authority"] = "runtime_probe"

        with self.assertRaisesRegex(ValueError, "fact authority"):
            build_context_readiness_status_summary(source)

    def test_fact_basis_and_non_claim_vocabulary_are_enforced(self) -> None:
        source = _load_input()
        source["context_records"][0]["status_facts"][0]["basis"] = ""

        with self.assertRaisesRegex(ValueError, "basis"):
            build_context_readiness_status_summary(source)

        source = _load_input()
        source["context_records"][0]["status_facts"][0]["does_not_claim"] = "run_ready"

        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            build_context_readiness_status_summary(source)


if __name__ == "__main__":
    unittest.main()
