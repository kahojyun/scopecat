from __future__ import annotations

import unittest

import scopecat.calibration_continuation as calibration_continuation


class CalibrationContinuationPublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in calibration_continuation.__all__:
            self.assertTrue(hasattr(calibration_continuation, name), name)

    def test_private_helpers_are_not_top_level_exports(self) -> None:
        private_names = {
            "_EXPECTED_POLICY",
            "_FORBIDDEN_KEYS",
            "_records_by_key",
            "_reject_forbidden_keys",
            "_validate_references",
        }

        self.assertFalse(private_names.intersection(calibration_continuation.__all__))
        for name in private_names:
            self.assertFalse(hasattr(calibration_continuation, name), name)

    def test_promoted_route_exports_review_surface_and_action_recording(self) -> None:
        expected_names = {
            "CalibrationContinuationReviewSurfaceRequest",
            "CalibrationReviewActionRecordingRequest",
            "build_calibration_continuation_review_surface_summary",
            "build_calibration_review_action_recording_summary",
            "compose_calibration_continuation_review_surface",
            "record_calibration_review_actions",
        }

        self.assertTrue(expected_names.issubset(calibration_continuation.__all__))


if __name__ == "__main__":
    unittest.main()
