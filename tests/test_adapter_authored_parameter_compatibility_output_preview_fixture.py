from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "adapter_authored_parameter_compatibility_output_preview"
    / "basic_preview"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "preview-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-preview-summary.json").read_text(encoding="utf-8"))


class AdapterAuthoredParameterCompatibilityOutputPreviewFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "preview-input.json",
            FIXTURE / "expected-preview-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("file observation", expected["decisions_not_earned"])
        self.assertIn("stable public adapter API", expected["decisions_not_earned"])
        self.assertIn(
            "without owning the external format",
            expected["reference_semantics"]["adapter_boundary"],
        )

    def test_manifest_identity_matches_request_summary(self) -> None:
        source = _input_fixture()
        request = source["adapter_request_summary"]["adapter_request"]
        manifest = source["adapter_output_manifest"]

        self.assertEqual(manifest["request_id"], request["request_id"])
        self.assertEqual(manifest["approval_id"], request["approval_id"])
        self.assertEqual(manifest["prepared_run_context_id"], request["prepared_run_context_id"])
        self.assertEqual(manifest["measurement_id"], request["measurement_id"])
        self.assertEqual(manifest["parameter_state_id"], request["parameter_state_id"])

    def test_expected_summary_preserves_adapter_declared_external_target(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["classification"], "adapter_compatibility_output_ready_for_review"
        )
        self.assertEqual(candidate["target"]["target_authority"], "adapter_declared")
        self.assertEqual(candidate["target"]["scopecat_external_file_authority"], "not_claimed")
        self.assertEqual(candidate["preview_effects"]["file_observation"], "not_performed")


if __name__ == "__main__":
    unittest.main()
