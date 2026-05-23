from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.new_run_measurement_writer import (
    build_new_run_measurement_writer_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "new_run_measurement_writer" / "basic_1d_run"


def _load_input() -> dict:
    return json.loads((FIXTURE / "new-run-writer-input.json").read_text(encoding="utf-8"))


class NewRunMeasurementWriterSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_new_run_measurement_writer_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-new-run-writer-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_completed_measurement_progress_is_derived_from_writer_events(self) -> None:
        summary = build_new_run_measurement_writer_summary(_load_input())
        record = summary["measurement_record"]

        self.assertEqual(record["lifecycle"]["state"], "completed")
        self.assertEqual(record["progress"]["recorded_points"], 5)
        self.assertTrue(record["progress"]["complete"])
        self.assertEqual(record["classification"], "recorded_ready_for_review")

    def test_boundary_output_keeps_storage_hardware_and_schema_inference_out_of_scope(
        self,
    ) -> None:
        expected = json.loads(
            (FIXTURE / "expected-new-run-writer-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not storage mutation", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["writer_policy"]["storage_mutation"], "not_performed")
        self.assertEqual(
            attention["hardware_control_not_performed"]["does_not_claim"],
            "instrument_command_or_safety_authority",
        )
        self.assertIn(
            "append-only storage writer",
            " ".join(expected["decisions_not_earned"]),
        )

    def test_failed_measurement_remains_reviewable_without_retry_policy(self) -> None:
        source = _load_input()
        source["writer_events"][-1] = {
            "event_id": "evt-3001-failed",
            "event_type": "measurement_failed",
            "occurred_at": "2026-02-10T14:20:14Z",
            "measurement_record_id": "run-3001-rabi",
            "final_recorded_points": 5,
            "reason": "Operator stopped the run after reviewing the last recorded row.",
        }

        summary = build_new_run_measurement_writer_summary(source)

        self.assertEqual(summary["measurement_record"]["lifecycle"]["state"], "failed")
        self.assertEqual(
            summary["measurement_record"]["classification"],
            "failed_record_needs_review",
        )
        self.assertEqual(summary["writer_findings"][0]["finding"], "measurement_failed")
        self.assertEqual(
            summary["writer_findings"][0]["does_not_claim"],
            "hardware_failure_or_retry_policy",
        )

    def test_positive_storage_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["writer_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_new_run_measurement_writer_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["writer_policy"]["append_only_store"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_new_run_measurement_writer_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_new_run_measurement_writer_summary(source)

        source["primary_data"]["path"] = "mutated"
        source["declared_preview_metadata"]["declared_columns"][0]["label"] = "mutated"
        source["writer_events"][1]["rows_recorded"] = 999

        self.assertEqual(
            summary["measurement_record"]["primary_data"]["path"],
            "source/new-run-demo/run-3001-rabi-source.csv",
        )
        self.assertEqual(
            summary["measurement_record"]["preview"]["declared_roles"][0]["label"],
            "Drive amplitude",
        )
        self.assertEqual(summary["writer_events"][1]["rows_recorded"], 3)

    def test_duplicate_event_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["writer_events"][1])
        source["writer_events"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            build_new_run_measurement_writer_summary(source)

    def test_first_event_must_start_measurement(self) -> None:
        source = _load_input()
        source["writer_events"][0], source["writer_events"][1] = (
            source["writer_events"][1],
            source["writer_events"][0],
        )

        with self.assertRaisesRegex(ValueError, "first writer event"):
            build_new_run_measurement_writer_summary(source)

    def test_final_event_must_be_last(self) -> None:
        source = _load_input()
        source["writer_events"][2], source["writer_events"][3] = (
            source["writer_events"][3],
            source["writer_events"][2],
        )

        with self.assertRaisesRegex(ValueError, "last writer event"):
            build_new_run_measurement_writer_summary(source)

    def test_completed_measurement_must_record_expected_points(self) -> None:
        source = _load_input()
        source["writer_events"][2]["rows_recorded"] = 1
        source["writer_events"][2]["total_rows_recorded"] = 4
        source["writer_events"][-1]["final_recorded_points"] = 4

        with self.assertRaisesRegex(ValueError, "expected points"):
            build_new_run_measurement_writer_summary(source)

    def test_data_recorded_total_must_match_rows_recorded_increment(self) -> None:
        source = _load_input()
        source["writer_events"][1]["total_rows_recorded"] = 4

        with self.assertRaisesRegex(ValueError, "previous total plus rows_recorded"):
            build_new_run_measurement_writer_summary(source)

    def test_event_timestamps_must_be_monotonic(self) -> None:
        source = _load_input()
        source["writer_events"][2]["occurred_at"] = "2026-02-10T14:20:07Z"

        with self.assertRaisesRegex(ValueError, "timestamps"):
            build_new_run_measurement_writer_summary(source)

    def test_data_recorded_path_must_match_primary_data(self) -> None:
        source = _load_input()
        source["writer_events"][1]["primary_data_path"] = "source/new-run-demo/wrong.csv"

        with self.assertRaisesRegex(ValueError, "data-recorded event path"):
            build_new_run_measurement_writer_summary(source)

    def test_primary_data_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["primary_data"]["path"] = "/private/run.csv"

        with self.assertRaisesRegex(ValueError, "primary data path"):
            build_new_run_measurement_writer_summary(source)

    def test_primary_data_kind_and_format_are_bounded(self) -> None:
        source = _load_input()
        source["primary_data"]["kind"] = "derived_artifact"

        with self.assertRaisesRegex(ValueError, "primary data kind"):
            build_new_run_measurement_writer_summary(source)

        source = _load_input()
        source["primary_data"]["format"] = "binary_blob"

        with self.assertRaisesRegex(ValueError, "primary data format"):
            build_new_run_measurement_writer_summary(source)

    def test_preview_metadata_authority_must_stay_writer_declared(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["metadata_authority"] = "source_parser"

        with self.assertRaisesRegex(ValueError, "metadata authority"):
            build_new_run_measurement_writer_summary(source)

    def test_preview_axes_must_reference_declared_columns(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["plot_candidates"][0]["y"] = "undeclared_signal"

        with self.assertRaisesRegex(ValueError, "declared columns"):
            build_new_run_measurement_writer_summary(source)

    def test_preview_declared_column_names_must_be_unique(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["declared_columns"][1]["name"] = "drive_amplitude"

        with self.assertRaisesRegex(ValueError, "unique names"):
            build_new_run_measurement_writer_summary(source)

    def test_degraded_preview_does_not_carry_inferred_columns(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"] = {
            "status": "degraded_preview",
            "metadata_authority": "writer_declared",
            "data_shape": None,
            "declared_columns": [
                {
                    "name": "drive_amplitude",
                    "role": "sweep_axis",
                    "label": "Drive amplitude",
                    "unit": "a.u.",
                }
            ],
            "plot_candidates": [],
            "warning_code": "preview_metadata_missing",
            "message": "Writer did not declare enough preview metadata.",
        }

        with self.assertRaisesRegex(ValueError, "degraded preview"):
            build_new_run_measurement_writer_summary(source)

    def test_failed_measurement_requires_reason(self) -> None:
        source = _load_input()
        source["writer_events"][-1] = {
            "event_id": "evt-3001-failed",
            "event_type": "measurement_failed",
            "occurred_at": "2026-02-10T14:20:14Z",
            "measurement_record_id": "run-3001-rabi",
            "final_recorded_points": 5,
            "reason": "",
        }

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_new_run_measurement_writer_summary(source)

    def test_completed_measurement_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["writer_events"][-1]["reason"] = "completed cleanly"

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_new_run_measurement_writer_summary(source)


if __name__ == "__main__":
    unittest.main()
