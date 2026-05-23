from __future__ import annotations

import copy
import csv
import json
import unittest
from pathlib import Path

from implementation_candidates.derived_artifact_source_links import (
    build_derived_artifact_source_link_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "derived_artifact_source_links" / "basic_artifact_links"


def _load_input() -> dict:
    return json.loads((FIXTURE / "artifact-links-input.json").read_text(encoding="utf-8"))


class DerivedArtifactSourceLinksSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_derived_artifact_source_link_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-artifact-link-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_fixture_artifact_is_openable_but_not_parsed_by_builder(self) -> None:
        source = _load_input()
        artifact_path = FIXTURE / source["artifact"]["path"]

        with artifact_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["fit_parameter"], "rabi_frequency")

    def test_boundary_keeps_artifact_parsing_and_dag_inference_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-artifact-link-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not an artifact parser", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["artifact_link_policy"]["analysis_dag_inference"],
            "not_performed",
        )
        self.assertEqual(
            attention["analysis_dag_not_inferred"]["does_not_claim"],
            "recursive_analysis_dag",
        )
        self.assertIn(
            "scientific validity or fit-quality review",
            expected["decisions_not_earned"],
        )

    def test_unavailable_source_is_review_finding_not_lineage_claim(self) -> None:
        summary = build_derived_artifact_source_link_summary(_load_input())
        finding = summary["link_findings"][0]

        self.assertEqual(summary["classification"], "needs_source_review")
        self.assertEqual(finding["finding"], "source_measurement_unavailable")
        self.assertEqual(finding["does_not_claim"], "analysis_lineage_invalid_or_complete")

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_derived_artifact_source_link_summary(source)

        source["artifact"]["label"] = "mutated"
        source["source_measurements"][0]["primary_data_reference"]["path"] = "mutated"

        self.assertEqual(summary["artifact"]["label"], "Rabi fit summary")
        self.assertEqual(
            summary["source_links"][0]["primary_data_reference"]["path"],
            "source/export-demo-session/measurement-1001-rabi-source.csv",
        )

    def test_checksum_and_storage_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_link_policy"]["checksum_validation"] = "performed"

        with self.assertRaisesRegex(ValueError, "checksum_validation"):
            build_derived_artifact_source_link_summary(source)

        source = _load_input()
        source["artifact_link_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_derived_artifact_source_link_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_link_policy"]["artifact_parser"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_derived_artifact_source_link_summary(source)

    def test_duplicate_source_measurement_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["source_measurements"][0])
        source["source_measurements"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate measurement_id"):
            build_derived_artifact_source_link_summary(source)

    def test_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["artifact"]["path"] = "/private/artifacts/rabi-fit-summary.csv"

        with self.assertRaisesRegex(ValueError, "artifact path"):
            build_derived_artifact_source_link_summary(source)

        source = _load_input()
        source["source_measurements"][0]["primary_data_reference"]["path"] = "../source.csv"

        with self.assertRaisesRegex(ValueError, "primary data reference path"):
            build_derived_artifact_source_link_summary(source)

    def test_primary_data_reference_extra_fields_are_rejected(self) -> None:
        source = _load_input()
        source["source_measurements"][0]["primary_data_reference"]["sha256"] = "not-validated"

        with self.assertRaisesRegex(ValueError, "primary data reference"):
            build_derived_artifact_source_link_summary(source)

    def test_unavailable_source_requires_reason(self) -> None:
        source = _load_input()
        source["source_measurements"][1]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_derived_artifact_source_link_summary(source)

    def test_available_source_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["source_measurements"][0]["reason"] = "unexpected"

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_derived_artifact_source_link_summary(source)

    def test_authority_must_stay_explicit_manifest(self) -> None:
        source = _load_input()
        source["source_measurements"][0]["authority"] = "analysis_engine"

        with self.assertRaisesRegex(ValueError, "source link authority"):
            build_derived_artifact_source_link_summary(source)

    def test_unsupported_role_and_relation_are_rejected(self) -> None:
        source = _load_input()
        source["source_measurements"][0]["source_role"] = "upstream_parent"

        with self.assertRaisesRegex(ValueError, "source_role"):
            build_derived_artifact_source_link_summary(source)

        source = _load_input()
        source["source_measurements"][0]["relation"] = "inferred_from_notebook"

        with self.assertRaisesRegex(ValueError, "relation"):
            build_derived_artifact_source_link_summary(source)

    def test_unavailable_artifact_requires_artifact_review_classification(self) -> None:
        source = _load_input()
        source["artifact"]["reference_state"] = "unavailable"
        source["artifact"]["reason"] = "The artifact file was not included in the review drop."
        source["source_measurements"][1]["record_state"] = "declared_available"
        source["source_measurements"][1]["reason"] = None

        summary = build_derived_artifact_source_link_summary(source)

        self.assertEqual(summary["classification"], "needs_artifact_review")
        self.assertEqual(summary["link_findings"][0]["finding"], "artifact_unavailable")

    def test_redacted_artifact_requires_artifact_review_classification(self) -> None:
        source = _load_input()
        source["artifact"]["reference_state"] = "redacted"
        source["artifact"]["reason"] = "The artifact content was intentionally excluded."
        source["source_measurements"][1]["record_state"] = "declared_available"
        source["source_measurements"][1]["reason"] = None

        summary = build_derived_artifact_source_link_summary(source)

        self.assertEqual(summary["classification"], "needs_artifact_review")
        self.assertEqual(summary["link_findings"][0]["finding"], "artifact_redacted")

    def test_recursive_source_shape_is_rejected(self) -> None:
        source = _load_input()
        source["source_measurements"][0]["upstream_sources"] = ["measurement-older"]

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_derived_artifact_source_link_summary(source)


if __name__ == "__main__":
    unittest.main()
