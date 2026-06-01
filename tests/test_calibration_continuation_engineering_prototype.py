from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.calibration_continuation import (
    CalibrationContinuationReviewSurfaceRequest,
    CalibrationReviewActionRecordingRequest,
    build_calibration_continuation_review_surface_summary,
    build_calibration_review_action_recording_summary,
    compose_calibration_continuation_review_surface,
    record_calibration_review_actions,
)

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


class CalibrationContinuationEngineeringPrototypeTest(unittest.TestCase):
    def test_review_surface_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = (
            ROOT
            / "tests"
            / "fixtures"
            / "calibration_continuation_review_surface"
            / "basic_surface"
        )
        source = _read_json(fixture / "surface-input.json")
        request = CalibrationContinuationReviewSurfaceRequest.from_dict(source)
        result = compose_calibration_continuation_review_surface(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-surface-summary.json"),
        )
        self.assertEqual(result.route_header["surface_state"], "blocked_with_context_findings")
        self.assertEqual(
            build_calibration_continuation_review_surface_summary(source),
            result.to_dict(),
        )

    def test_action_recording_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"
        )
        source = _read_json(fixture / "action-recording-input.json")
        request = CalibrationReviewActionRecordingRequest.from_dict(source)
        result = record_calibration_review_actions(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-action-recording-summary.json"),
        )
        self.assertEqual(
            result.recording_classification,
            "review_action_choices_recorded_without_execution",
        )
        self.assertEqual(
            build_calibration_review_action_recording_summary(source),
            result.to_dict(),
        )

    def test_review_surface_rejects_executable_action_payloads(self) -> None:
        fixture = (
            ROOT
            / "tests"
            / "fixtures"
            / "calibration_continuation_review_surface"
            / "basic_surface"
        )
        source = _read_json(fixture / "surface-input.json")
        source["review_state_summary"]["review_cards"][0]["command"] = "run-notebook-cell"

        with self.assertRaisesRegex(ValueError, "must not include command"):
            CalibrationContinuationReviewSurfaceRequest.from_dict(source)

    def test_review_surface_rejects_missing_selected_step(self) -> None:
        fixture = (
            ROOT
            / "tests"
            / "fixtures"
            / "calibration_continuation_review_surface"
            / "basic_surface"
        )
        source = _read_json(fixture / "surface-input.json")
        source["surface_request"]["selected_step_id"] = "missing-step"

        with self.assertRaisesRegex(ValueError, "selected step must exist"):
            build_calibration_continuation_review_surface_summary(source)

    def test_action_recording_rejects_unavailable_surface_label(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"
        )
        source = _read_json(fixture / "action-recording-input.json")
        source["action_events"][0]["action_label"] = "execute_unlisted_action"

        with self.assertRaisesRegex(ValueError, "available surface action label"):
            build_calibration_review_action_recording_summary(source)

    def test_action_recording_rejects_execution_state(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"
        )
        source = _read_json(fixture / "action-recording-input.json")
        source["action_events"][0]["execution_state"] = "executed"

        with self.assertRaisesRegex(ValueError, "must not execute"):
            CalibrationReviewActionRecordingRequest.from_dict(source)

    def test_action_recording_orders_events_without_mutating_input(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"
        )
        source = _read_json(fixture / "action-recording-input.json")
        source["action_events"] = list(reversed(source["action_events"]))
        original = copy.deepcopy(source)

        result = build_calibration_review_action_recording_summary(source)

        self.assertEqual([event["order"] for event in result["recorded_events"]], [1, 2])
        self.assertEqual(source, original)


if __name__ == "__main__":
    unittest.main()
