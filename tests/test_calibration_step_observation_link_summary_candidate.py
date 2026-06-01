from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_step_observation_link import (
    build_calibration_step_observation_link_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_step_observation_link" / "basic_observation"


def _load_input() -> dict:
    return json.loads((FIXTURE / "observation-link-input.json").read_text(encoding="utf-8"))


class CalibrationStepObservationLinkSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_step_observation_link_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-observation-link-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_intent_and_record_postures_are_distinct(self) -> None:
        summary = build_calibration_step_observation_link_summary(_load_input())

        self.assertEqual(
            summary["calibration_step_intents"][0]["intent_posture"],
            "prospective_observation_need",
        )
        self.assertEqual(
            summary["calibration_step_records"][0]["record_posture"],
            "retrospective_observation_summary",
        )

    def test_linked_measurement_is_summary_projection_only(self) -> None:
        summary = build_calibration_step_observation_link_summary(_load_input())
        link = summary["calibration_step_records"][0]["observation_links"][0]
        projection = link["measurement_projection"]

        self.assertEqual(link["measurement_record_id"], "measurement-07001")
        self.assertEqual(
            link["link_semantics"],
            "calibration_step_observed_measurement_reference",
        )
        self.assertEqual(projection["primary_data_owner"], "measurement_records")
        self.assertNotIn("primary_data", projection)

    def test_missing_measurement_is_finding_not_retry_or_failure(self) -> None:
        summary = build_calibration_step_observation_link_summary(_load_input())
        record = summary["calibration_step_records"][1]
        finding = summary["missing_observation_findings"][0]

        self.assertEqual(record["missing_measurement_count"], 1)
        self.assertEqual(finding["finding"], "measurement_observation_missing")
        self.assertEqual(
            finding["does_not_claim"],
            "calibration_step_invalid_or_retry_required",
        )

    def test_boundary_attention_keeps_execution_fit_and_write_back_out_of_scope(self) -> None:
        summary = build_calibration_step_observation_link_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            attention["measurement_records_own_primary_data"]["does_not_claim"],
            "calibration_owns_measurement_payload",
        )
        self.assertEqual(
            attention["fit_execution_not_performed"]["does_not_claim"],
            "fit_result_or_quality_score",
        )
        self.assertEqual(
            attention["write_back_not_performed"]["does_not_claim"],
            "parameter_update",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["observation_link_policy"]["fit_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "fit_execution"):
            build_calibration_step_observation_link_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["observation_link_policy"]["fit_quality_score"] = "computed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_step_observation_link_summary(source)

    def test_planned_observation_must_not_require_payload_reads(self) -> None:
        source = _load_input()
        source["calibration_step_intents"][0]["planned_observation"][
            "measurement_payload_required"
        ] = True

        with self.assertRaisesRegex(ValueError, "payload reads"):
            build_calibration_step_observation_link_summary(source)

    def test_step_record_must_reference_existing_intent(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["step_intent_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing intent"):
            build_calibration_step_observation_link_summary(source)

    def test_linked_measurement_must_reference_existing_measurement_summary(self) -> None:
        source = _load_input()
        source["calibration_step_records"][0]["observation_links"][0]["measurement_record_id"] = (
            "missing"
        )

        with self.assertRaisesRegex(ValueError, "missing measurement"):
            build_calibration_step_observation_link_summary(source)

    def test_missing_observation_must_not_carry_measurement_id(self) -> None:
        source = _load_input()
        source["calibration_step_records"][1]["observation_links"][0]["measurement_record_id"] = (
            "measurement-07001"
        )

        with self.assertRaisesRegex(ValueError, "must not carry"):
            build_calibration_step_observation_link_summary(source)

    def test_missing_observation_requires_reason(self) -> None:
        source = _load_input()
        source["calibration_step_records"][1]["observation_links"][0].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "missing_reason"):
            build_calibration_step_observation_link_summary(source)

    def test_duplicate_link_ids_within_step_record_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["calibration_step_records"][0]["observation_links"][0])
        source["calibration_step_records"][0]["observation_links"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_calibration_step_observation_link_summary(source)

    def test_measurement_summary_authority_must_stay_measurement_records(self) -> None:
        source = _load_input()
        source["measurement_record_summaries"][0]["primary_data_owner"] = "calibration"

        with self.assertRaisesRegex(ValueError, "primary data owner"):
            build_calibration_step_observation_link_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_step_observation_link_summary(source)

        source["calibration_step_intents"][0]["planned_observation"]["target"] = "mutated"
        source["measurement_record_summaries"][0]["preview_status"] = "mutated"
        source["calibration_step_records"][0]["observation_links"][0]["measurement_record_id"] = (
            "mutated"
        )

        self.assertEqual(
            summary["calibration_step_intents"][0]["planned_observation"]["target"],
            "qA",
        )
        self.assertEqual(
            summary["measurement_record_summaries"][0]["preview_status"],
            "preview_ready",
        )
        self.assertEqual(
            summary["calibration_step_records"][0]["observation_links"][0]["measurement_record_id"],
            "measurement-07001",
        )


if __name__ == "__main__":
    unittest.main()
