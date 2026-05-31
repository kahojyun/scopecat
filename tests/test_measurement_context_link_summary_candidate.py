from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.measurement_context_link import (
    build_measurement_context_link_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_context_link" / "basic_optional_links"


def _load_input() -> dict:
    return json.loads((FIXTURE / "context-link-input.json").read_text(encoding="utf-8"))


class MeasurementContextLinkSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_measurement_context_link_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-context-link-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_zero_context_measurement_record_remains_valid(self) -> None:
        summary = build_measurement_context_link_summary(_load_input())
        record = summary["measurement_records"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(record["measurement_record_id"], "measurement-06001")
        self.assertEqual(record["context_link_count"], 0)
        self.assertEqual(record["context_policy"], "valid_without_context")
        self.assertEqual(record["classification"], "measurement_record_valid_for_review")
        self.assertEqual(
            attention["zero_context_measurement_records_allowed"]["does_not_claim"],
            "context_required_for_primary_data_validity",
        )

    def test_linked_context_is_reference_only(self) -> None:
        summary = build_measurement_context_link_summary(_load_input())
        refs = summary["linked_context_refs"]

        self.assertEqual(refs[0]["measurement_record_id"], "measurement-06002")
        self.assertEqual(refs[0]["context_id"], "param-state-0007")
        self.assertEqual(refs[0]["link_semantics"], "reference_only_context_link")
        self.assertNotIn("declared_summary", refs[0])

    def test_missing_optional_context_is_finding_not_invalid_record(self) -> None:
        summary = build_measurement_context_link_summary(_load_input())
        record = summary["measurement_records"][2]
        finding = summary["optional_context_findings"][0]

        self.assertEqual(record["measurement_record_id"], "measurement-06003")
        self.assertEqual(record["missing_optional_context_count"], 1)
        self.assertEqual(record["classification"], "measurement_record_valid_for_review")
        self.assertEqual(finding["finding"], "optional_context_unavailable")
        self.assertEqual(finding["does_not_claim"], "measurement_record_invalid")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["context_link_policy"]["recursive_traversal"] = "performed"

        with self.assertRaisesRegex(ValueError, "recursive_traversal"):
            build_measurement_context_link_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["context_link_policy"]["context_readiness"] = "required"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_measurement_context_link_summary(source)

    def test_context_links_must_remain_optional_for_record_validity(self) -> None:
        source = _load_input()
        source["measurement_records"][1]["context_links"][0]["required_for_record_validity"] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record"):
            build_measurement_context_link_summary(source)

    def test_linked_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["measurement_records"][1]["context_links"][0]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing context"):
            build_measurement_context_link_summary(source)

    def test_linked_context_family_must_match(self) -> None:
        source = _load_input()
        source["measurement_records"][1]["context_links"][0]["context_id"] = "setup-binding-0002"

        with self.assertRaisesRegex(ValueError, "wrong family"):
            build_measurement_context_link_summary(source)

    def test_unavailable_optional_context_needs_reason(self) -> None:
        source = _load_input()
        source["measurement_records"][2]["context_links"][0].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "missing_reason"):
            build_measurement_context_link_summary(source)

    def test_unlinked_optional_context_must_not_carry_context_id(self) -> None:
        source = _load_input()
        source["measurement_records"][2]["context_links"][0]["context_id"] = "param-state-0007"

        with self.assertRaisesRegex(ValueError, "must not carry"):
            build_measurement_context_link_summary(source)

    def test_duplicate_measurement_record_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["measurement_records"][0])
        source["measurement_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate measurement_record_id"):
            build_measurement_context_link_summary(source)

    def test_duplicate_context_link_ids_within_record_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["measurement_records"][1]["context_links"][0])
        source["measurement_records"][1]["context_links"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_measurement_context_link_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_measurement_context_link_summary(source)

        source["context_records"][0]["declared_summary"]["trusted_entry_count"] = 99
        source["measurement_records"][1]["primary_data"]["path"] = "mutated"
        source["measurement_records"][1]["context_links"][0]["context_id"] = "mutated"

        self.assertEqual(
            summary["context_records"][0]["declared_summary"]["trusted_entry_count"],
            4,
        )
        self.assertEqual(
            summary["measurement_records"][1]["primary_data"]["path"],
            "records/measurement-06002/primary.csv",
        )
        self.assertEqual(summary["linked_context_refs"][0]["context_id"], "param-state-0007")


if __name__ == "__main__":
    unittest.main()
