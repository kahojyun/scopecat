from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.supporting_evidence_reference import (
    build_supporting_evidence_reference_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "supporting_evidence_reference"
    / "basic_supporting_evidence_reference"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "supporting-evidence-input.json").read_text(encoding="utf-8"))


class SupportingEvidenceReferenceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_supporting_evidence_reference_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-supporting-evidence-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_fixture_evidence_is_openable_but_not_imported_by_builder(self) -> None:
        source = _load_input()
        evidence_path = FIXTURE / source["evidence"]["declared_reference"]["value"]

        self.assertIn("Synthetic stderr excerpt", evidence_path.read_text(encoding="utf-8"))
        summary = build_supporting_evidence_reference_summary(source)

        self.assertNotIn("payload", summary["evidence"])
        self.assertEqual(summary["supporting_evidence_policy"]["payload_import"], "not_performed")
        self.assertEqual(summary["supporting_evidence_policy"]["file_observation"], "not_performed")

    def test_boundary_keeps_evidence_out_of_canonical_context(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-supporting-evidence-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("attachment/artifact", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["supporting_evidence_policy"]["evidence_context_role"],
            "supporting_evidence_not_canonical_context",
        )
        self.assertEqual(
            attention["evidence_not_canonical_context"]["does_not_claim"],
            "parameter_or_measurement_context_authority",
        )
        self.assertIn("general attachment subsystem", expected["decisions_not_earned"])

    def test_evidence_kind_is_label_only_without_artifact_provenance(self) -> None:
        summary = build_supporting_evidence_reference_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["evidence"]["evidence_kind"], "attachment")
        self.assertEqual(
            summary["supporting_evidence_policy"]["artifact_provenance"],
            "not_required_without_artifact_provenance_slice",
        )
        self.assertEqual(
            attention["evidence_kind_is_label_only"]["does_not_claim"],
            "artifact_provenance_complete",
        )

    def test_lifecycle_stage_is_explicit_and_not_run_start_context(self) -> None:
        summary = build_supporting_evidence_reference_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["evidence"]["lifecycle_stage"], "during_run")
        self.assertEqual(
            summary["supporting_links"][0]["evidence_lifecycle_stage"],
            "during_run",
        )
        self.assertEqual(
            attention["evidence_lifecycle_is_explicit"]["does_not_claim"],
            "run_start_context_requirement",
        )

    def test_unavailable_target_is_review_finding_not_validity_claim(self) -> None:
        summary = build_supporting_evidence_reference_summary(_load_input())
        finding = summary["reference_findings"][0]

        self.assertEqual(summary["classification"], "needs_related_target_review")
        self.assertEqual(finding["finding"], "related_target_unavailable")
        self.assertEqual(finding["does_not_claim"], "measurement_or_context_invalid")

    def test_ready_classification_when_evidence_and_targets_are_available(self) -> None:
        source = _load_input()
        source["related_targets"][2]["target_state"] = "resolved"
        source["related_targets"][2]["reason"] = None

        summary = build_supporting_evidence_reference_summary(source)

        self.assertEqual(summary["classification"], "ready_for_supporting_evidence_review")
        self.assertEqual(summary["reference_findings"], [])

    def test_artifact_kind_can_be_label_only_without_provenance(self) -> None:
        source = _load_input()
        source["evidence"]["evidence_kind"] = "artifact"
        source["related_targets"][2]["target_state"] = "resolved"
        source["related_targets"][2]["reason"] = None

        summary = build_supporting_evidence_reference_summary(source)

        self.assertEqual(summary["evidence"]["evidence_kind"], "artifact")
        self.assertEqual(summary["classification"], "ready_for_supporting_evidence_review")
        self.assertNotIn("provenance", summary["evidence"])

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_supporting_evidence_reference_summary(source)

        source["evidence"]["declared_reference"]["value"] = "mutated"
        source["related_targets"][0]["label"] = "mutated"

        self.assertEqual(
            summary["evidence"]["declared_reference"]["value"],
            "artifacts/rabi-run-stderr-excerpt.txt",
        )
        self.assertEqual(summary["supporting_links"][0]["label"], "Running Rabi measurement")

    def test_payload_import_and_file_observation_claims_are_rejected(self) -> None:
        source = _load_input()
        source["supporting_evidence_policy"]["payload_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["supporting_evidence_policy"]["file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "file_observation"):
            build_supporting_evidence_reference_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["supporting_evidence_policy"]["evidence_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_evidence_reference_summary(source)

    def test_payload_and_provenance_passthrough_are_rejected(self) -> None:
        source = _load_input()
        source["evidence"]["payload"] = {"debug": "not imported"}

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["evidence"]["provenance"] = {"source": "not validated here"}

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_evidence_reference_summary(source)

    def test_duplicate_targets_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["related_targets"][0])
        source["related_targets"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate supporting evidence target"):
            build_supporting_evidence_reference_summary(source)

    def test_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["evidence"]["declared_reference"]["value"] = "/private/debug-note.md"

        with self.assertRaisesRegex(ValueError, "evidence reference path"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["evidence"]["declared_reference"]["value"] = "../debug-note.md"

        with self.assertRaisesRegex(ValueError, "evidence reference path"):
            build_supporting_evidence_reference_summary(source)

    def test_unavailable_evidence_requires_evidence_reference_review(self) -> None:
        source = _load_input()
        reference = source["evidence"]["declared_reference"]
        reference["reference_state"] = "unavailable"
        reference["reason"] = "The debug evidence was not supplied with the review packet."
        source["related_targets"][2]["target_state"] = "resolved"
        source["related_targets"][2]["reason"] = None

        summary = build_supporting_evidence_reference_summary(source)

        self.assertEqual(summary["classification"], "needs_evidence_reference_review")
        self.assertEqual(
            summary["reference_findings"][0]["finding"],
            "evidence_reference_unavailable",
        )

    def test_available_evidence_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["evidence"]["declared_reference"]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_supporting_evidence_reference_summary(source)

    def test_target_state_reason_rules_are_enforced(self) -> None:
        source = _load_input()
        source["related_targets"][2]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["related_targets"][0]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "resolved target"):
            build_supporting_evidence_reference_summary(source)

    def test_unsupported_evidence_kind_and_lifecycle_stage_are_rejected(self) -> None:
        source = _load_input()
        source["evidence"]["evidence_kind"] = "debug_attachment"

        with self.assertRaisesRegex(ValueError, "evidence_kind"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["evidence"]["lifecycle_stage"] = "implicit_run_start"

        with self.assertRaisesRegex(ValueError, "lifecycle_stage"):
            build_supporting_evidence_reference_summary(source)

    def test_authority_and_supported_relation_are_enforced(self) -> None:
        source = _load_input()
        source["related_targets"][0]["authority"] = "adapter_output"

        with self.assertRaisesRegex(ValueError, "target authority"):
            build_supporting_evidence_reference_summary(source)

        source = _load_input()
        source["related_targets"][0]["relation"] = "derived_from_measurement"

        with self.assertRaisesRegex(ValueError, "relation"):
            build_supporting_evidence_reference_summary(source)


if __name__ == "__main__":
    unittest.main()
