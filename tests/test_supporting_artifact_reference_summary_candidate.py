from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.supporting_artifact_reference import (
    build_supporting_artifact_reference_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "supporting_artifact_reference"
    / "basic_supporting_artifact_reference"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "supporting-artifact-input.json").read_text(encoding="utf-8"))


class SupportingArtifactReferenceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_supporting_artifact_reference_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-supporting-artifact-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_fixture_artifact_is_openable_but_not_imported_by_builder(self) -> None:
        source = _load_input()
        artifact_path = FIXTURE / source["artifact"]["declared_reference"]["value"]

        self.assertIn("Parameter Write Debug Note", artifact_path.read_text(encoding="utf-8"))
        summary = build_supporting_artifact_reference_summary(source)

        self.assertNotIn("payload", summary["artifact"])
        self.assertEqual(summary["supporting_artifact_policy"]["payload_import"], "not_performed")
        self.assertEqual(summary["supporting_artifact_policy"]["file_observation"], "not_performed")

    def test_boundary_keeps_artifact_out_of_canonical_context(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-supporting-artifact-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not payload import", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["supporting_artifact_policy"]["artifact_context_role"],
            "supporting_evidence_not_canonical_context",
        )
        self.assertEqual(
            attention["artifact_not_canonical_context"]["does_not_claim"],
            "parameter_or_measurement_context_authority",
        )
        self.assertIn("general attachment subsystem", expected["decisions_not_earned"])

    def test_unavailable_target_is_review_finding_not_validity_claim(self) -> None:
        summary = build_supporting_artifact_reference_summary(_load_input())
        finding = summary["reference_findings"][0]

        self.assertEqual(summary["classification"], "needs_related_target_review")
        self.assertEqual(finding["finding"], "related_target_unavailable")
        self.assertEqual(finding["does_not_claim"], "measurement_or_context_invalid")

    def test_ready_classification_when_artifact_and_targets_are_available(self) -> None:
        source = _load_input()
        source["related_targets"][3]["target_state"] = "resolved"
        source["related_targets"][3]["reason"] = None

        summary = build_supporting_artifact_reference_summary(source)

        self.assertEqual(summary["classification"], "ready_for_supporting_artifact_review")
        self.assertEqual(summary["reference_findings"], [])

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_supporting_artifact_reference_summary(source)

        source["artifact"]["declared_reference"]["value"] = "mutated"
        source["related_targets"][0]["label"] = "mutated"

        self.assertEqual(
            summary["artifact"]["declared_reference"]["value"],
            "artifacts/parameter-write-debug-note.md",
        )
        self.assertEqual(summary["supporting_links"][0]["label"], "Accepted Rabi parameter state")

    def test_payload_import_and_file_observation_claims_are_rejected(self) -> None:
        source = _load_input()
        source["supporting_artifact_policy"]["payload_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_supporting_artifact_reference_summary(source)

        source = _load_input()
        source["supporting_artifact_policy"]["file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "file_observation"):
            build_supporting_artifact_reference_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["supporting_artifact_policy"]["artifact_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_artifact_reference_summary(source)

    def test_payload_passthrough_is_rejected(self) -> None:
        source = _load_input()
        source["artifact"]["payload"] = {"debug": "not imported"}

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_supporting_artifact_reference_summary(source)

    def test_duplicate_targets_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["related_targets"][0])
        source["related_targets"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate supporting artifact target"):
            build_supporting_artifact_reference_summary(source)

    def test_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["artifact"]["declared_reference"]["value"] = "/private/debug-note.md"

        with self.assertRaisesRegex(ValueError, "artifact reference path"):
            build_supporting_artifact_reference_summary(source)

        source = _load_input()
        source["artifact"]["declared_reference"]["value"] = "../debug-note.md"

        with self.assertRaisesRegex(ValueError, "artifact reference path"):
            build_supporting_artifact_reference_summary(source)

    def test_unavailable_artifact_requires_artifact_reference_review(self) -> None:
        source = _load_input()
        reference = source["artifact"]["declared_reference"]
        reference["reference_state"] = "unavailable"
        reference["reason"] = "The debug artifact was not supplied with the review packet."
        source["related_targets"][3]["target_state"] = "resolved"
        source["related_targets"][3]["reason"] = None

        summary = build_supporting_artifact_reference_summary(source)

        self.assertEqual(summary["classification"], "needs_artifact_reference_review")
        self.assertEqual(
            summary["reference_findings"][0]["finding"],
            "artifact_reference_unavailable",
        )

    def test_available_artifact_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["artifact"]["declared_reference"]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_supporting_artifact_reference_summary(source)

    def test_target_state_reason_rules_are_enforced(self) -> None:
        source = _load_input()
        source["related_targets"][3]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_supporting_artifact_reference_summary(source)

        source = _load_input()
        source["related_targets"][0]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "resolved target"):
            build_supporting_artifact_reference_summary(source)

    def test_authority_and_supported_relation_are_enforced(self) -> None:
        source = _load_input()
        source["related_targets"][0]["authority"] = "adapter_output"

        with self.assertRaisesRegex(ValueError, "target authority"):
            build_supporting_artifact_reference_summary(source)

        source = _load_input()
        source["related_targets"][0]["relation"] = "derived_from_measurement"

        with self.assertRaisesRegex(ValueError, "relation"):
            build_supporting_artifact_reference_summary(source)


if __name__ == "__main__":
    unittest.main()
