from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_continuation_composition"
    / "rabi_recovery_with_validation"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationFitContinuationCompositionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "composition-input.json",
            FIXTURE / "expected-composition-summary.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_input_embeds_continuation_and_fit_validation_context(self) -> None:
        source = _load_json(FIXTURE / "composition-input.json")

        self.assertIn("continuation_input", source)
        self.assertIn("fit_validation_input", source)
        self.assertIn("composition_links", source)
        self.assertNotIn("runner_log", source)
        self.assertNotIn("replay_harness", source)
        self.assertNotIn("fit_results", source)
        self.assertNotIn("score_contract", source)

    def test_fixture_links_recovery_to_continuation_and_validation(self) -> None:
        source = _load_json(FIXTURE / "composition-input.json")
        links = source["composition_links"]

        self.assertEqual(links["current_step_id"], "step-2-rabi-amplitude")
        self.assertEqual(links["next_step_id"], "step-3-t1-check")
        self.assertEqual(
            links["recovery_action_id"],
            "incident-rabi-recovered-for-continuation:accept_after_refit",
        )
        self.assertEqual(
            links["selected_attempt_ids"],
            [
                "fit-attempt:rabi-05002-default-failed",
                "fit-attempt:rabi-05002-roi-refit-accepted",
            ],
        )

    def test_expected_summary_declares_internal_validation_posture(self) -> None:
        expected = _load_json(FIXTURE / "expected-composition-summary.json")

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["reference_semantics"]["artifact_posture"],
            "internal_validation_summary",
        )
        self.assertIn("replay harness", expected["decisions_not_earned"])
        self.assertIn("dataset registry", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
