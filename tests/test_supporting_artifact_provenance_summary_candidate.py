from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.supporting_artifact_provenance import (
    build_supporting_artifact_provenance_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "supporting_artifact_provenance" / "basic_provenance"


def _load_input() -> dict:
    return json.loads((FIXTURE / "provenance-input.json").read_text(encoding="utf-8"))


class SupportingArtifactProvenanceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_supporting_artifact_provenance_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-provenance-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_boundary_keeps_provenance_declared_and_non_observing(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-provenance-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn(
            "declared producer and direct source links",
            expected["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(candidate["artifact_provenance_policy"]["payload_import"], "not_performed")
        self.assertEqual(
            candidate["artifact_provenance_policy"]["artifact_file_observation"],
            "not_performed",
        )
        self.assertEqual(
            attention["direct_sources_only"]["does_not_claim"],
            "recursive_analysis_dag",
        )
        self.assertIn("fit quality or scientific-validity review", expected["decisions_not_earned"])

    def test_unavailable_source_is_review_finding_not_lineage_or_validity_claim(self) -> None:
        summary = build_supporting_artifact_provenance_summary(_load_input())
        finding = summary["provenance_findings"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["classification"], "needs_artifact_source_review")
        self.assertEqual(finding["finding"], "artifact_source_unavailable")
        self.assertEqual(finding["does_not_claim"], "analysis_lineage_invalid_or_complete")
        self.assertEqual(
            attention["validity_not_claimed"]["does_not_claim"],
            "artifact_or_measurement_validity",
        )

    def test_ready_classification_when_all_declared_links_are_available(self) -> None:
        source = _load_input()
        source["source_links"][2]["source_state"] = "declared_available"
        source["source_links"][2]["reason"] = None

        summary = build_supporting_artifact_provenance_summary(source)

        self.assertEqual(summary["classification"], "ready_for_artifact_provenance_review")
        self.assertEqual(summary["provenance_findings"], [])

    def test_producer_review_classification_is_separate_from_source_review(self) -> None:
        source = _load_input()
        source["producer"]["execution_state"] = "unavailable"
        source["producer"]["reason"] = "The user did not supply the script run receipt."
        source["source_links"][2]["source_state"] = "declared_available"
        source["source_links"][2]["reason"] = None

        summary = build_supporting_artifact_provenance_summary(source)

        self.assertEqual(summary["classification"], "needs_artifact_producer_review")
        self.assertEqual(
            summary["provenance_findings"][0]["finding"],
            "artifact_producer_unavailable",
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_supporting_artifact_provenance_summary(source)

        source["producer"]["label"] = "mutated"
        source["source_links"][0]["label"] = "mutated"
        source["supporting_evidence_summary"]["evidence"]["declared_reference"]["value"] = "mutated"

        self.assertEqual(summary["producer"]["label"], "Rabi fit review script")
        self.assertEqual(summary["source_links"][0]["label"], "Completed Rabi measurement")
        self.assertEqual(
            summary["artifact"]["declared_reference"]["value"],
            "artifacts/rabi-fit-review.json",
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_provenance_policy"]["artifact_file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_file_observation"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["artifact_provenance_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_supporting_artifact_provenance_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_provenance_policy"]["artifact_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_artifact_provenance_summary(source)

    def test_supporting_evidence_summary_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["supporting_evidence_summary"]["supporting_evidence_policy"]["payload_import"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["supporting_evidence_summary"]["supporting_evidence_policy"][
            "artifact_provenance"
        ] = "validated_inline"

        with self.assertRaisesRegex(ValueError, "artifact_provenance"):
            build_supporting_artifact_provenance_summary(source)

    def test_supporting_evidence_must_be_artifact_labeled(self) -> None:
        source = _load_input()
        source["supporting_evidence_summary"]["evidence"]["evidence_kind"] = "attachment"

        with self.assertRaisesRegex(ValueError, "labeled as artifact"):
            build_supporting_artifact_provenance_summary(source)

    def test_artifact_identity_must_match_supporting_evidence(self) -> None:
        source = _load_input()
        source["artifact_identity"]["artifact_id"] = "other-artifact"

        with self.assertRaisesRegex(ValueError, "artifact_id"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["artifact_identity"]["declared_reference"]["value"] = "artifacts/other.json"

        with self.assertRaisesRegex(ValueError, "declared reference"):
            build_supporting_artifact_provenance_summary(source)

    def test_duplicate_source_links_are_rejected(self) -> None:
        source = _load_input()
        source["source_links"].append(copy.deepcopy(source["source_links"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate artifact source link"):
            build_supporting_artifact_provenance_summary(source)

    def test_source_state_reason_rules_are_enforced(self) -> None:
        source = _load_input()
        source["source_links"][2]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["source_links"][0]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_supporting_artifact_provenance_summary(source)

    def test_producer_state_reason_rules_are_enforced(self) -> None:
        source = _load_input()
        source["producer"]["execution_state"] = "redacted"

        with self.assertRaisesRegex(ValueError, "producer requires reason"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["producer"]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "producer must not carry reason"):
            build_supporting_artifact_provenance_summary(source)

    def test_unsupported_source_role_relation_and_authority_are_rejected(self) -> None:
        source = _load_input()
        source["source_links"][0]["source_role"] = "hidden_parent"

        with self.assertRaisesRegex(ValueError, "source_role"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["source_links"][0]["relation"] = "inferred_from_filename"

        with self.assertRaisesRegex(ValueError, "relation"):
            build_supporting_artifact_provenance_summary(source)

        source = _load_input()
        source["source_links"][0]["authority"] = "analysis_engine"

        with self.assertRaisesRegex(ValueError, "source authority"):
            build_supporting_artifact_provenance_summary(source)

    def test_recursive_source_shape_is_rejected(self) -> None:
        source = _load_input()
        source["source_links"][0]["upstream_sources"] = ["measurement-older"]

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_artifact_provenance_summary(source)


if __name__ == "__main__":
    unittest.main()
