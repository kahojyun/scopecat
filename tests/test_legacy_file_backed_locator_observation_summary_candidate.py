from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.legacy_file_backed_locator_observation import (
    observe_legacy_file_backed_locator,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "legacy_file_backed_locator_observation" / "basic_observation"
)
EXTERNAL_ROOT = FIXTURE / "external"


def _load_input() -> dict:
    return json.loads((FIXTURE / "locator-observation-input.json").read_text(encoding="utf-8"))


class LegacyFileBackedLocatorObservationSummaryCandidateTest(unittest.TestCase):
    def test_observes_expected_locator_without_data_claims(self) -> None:
        summary = observe_legacy_file_backed_locator(_load_input(), external_root=EXTERNAL_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-locator-observation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertEqual(summary["classification"], "legacy_file_backed_locator_observed")
        self.assertEqual(summary["observation_effects"]["data_observation"], "not_performed")
        self.assertEqual(
            summary["declared_preview_assertion"]["verification_state"],
            "not_verified_by_file_level_observation",
        )

    def test_input_is_not_mutated(self) -> None:
        source = _load_input()
        original = copy.deepcopy(source)

        observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(source, original)

    def test_missing_locator_file_is_review_finding_not_repair(self) -> None:
        source = _load_input()
        source["observation_request"]["source_path"] = "session-0001/missing.csv"

        summary = observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(
            summary["classification"], "legacy_file_backed_locator_unavailable_for_review"
        )
        self.assertEqual(summary["observed_legacy_source"]["status"], "unavailable")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["legacy_locator_source_unavailable"],
        )
        self.assertEqual(
            summary["review_findings"][0]["does_not_claim"],
            "reference_repair_or_moved_reference_discovery",
        )

    def test_digest_and_size_mismatches_are_review_findings(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        source["observation_request"]["expected_size_bytes"] = 5

        summary = observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(
            summary["classification"],
            "legacy_file_backed_locator_observed_with_file_fact_mismatch",
        )
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            [
                "legacy_locator_source_digest_mismatch",
                "legacy_locator_source_size_mismatch",
            ],
        )

    def test_expected_digest_and_size_can_be_unspecified(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = None
        source["observation_request"]["expected_size_bytes"] = None

        summary = observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(summary["classification"], "legacy_file_backed_locator_observed")
        self.assertEqual(summary["review_findings"], [])
        self.assertIsNone(summary["observed_legacy_source"]["expected_digest"])
        self.assertIsNone(summary["observed_legacy_source"]["expected_size_bytes"])

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_observation_policy"]["data_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "data_observation"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        source = _load_input()
        source["locator_observation_policy"]["reference_repair"] = "performed"

        with self.assertRaisesRegex(ValueError, "reference_repair"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_observation_policy"]["row_preview"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_request_must_select_source_sidecar_and_existing_target_locator(self) -> None:
        cases = [
            ("measurement_id", "other-measurement", "measurement_id"),
            ("target_id", "other-target", "target_id"),
            ("locator_id", "other-locator", "locator_id"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["observation_request"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_selected_locator_must_be_available_redacted_legacy_path(self) -> None:
        source = _load_input()
        source["observation_request"]["locator_id"] = "source-locator-record-0001"
        source["observation_request"]["target_id"] = "legacy-sidecar-measurement-0001"

        with self.assertRaisesRegex(ValueError, "legacy_path"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        source = _load_input()
        locator = source["legacy_sidecar_post_run_review_summary"]["review_sections"][
            "legacy_locators"
        ]["targets"][1]["locators"][0]
        locator["reference_state"] = "declared_unavailable"

        with self.assertRaisesRegex(ValueError, "declared_available"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

        source = _load_input()
        locator = source["legacy_sidecar_post_run_review_summary"]["review_sections"][
            "legacy_locators"
        ]["targets"][1]["locators"][0]
        locator["redacted"] = False

        with self.assertRaisesRegex(ValueError, "redacted"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_source_post_run_review_must_stay_non_mutating(self) -> None:
        source = _load_input()
        review_policy = source["legacy_sidecar_post_run_review_summary"][
            "sidecar_post_run_review_policy"
        ]
        review_policy["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_source_path_must_stay_relative(self) -> None:
        source = _load_input()
        source["observation_request"]["source_path"] = "../session-0001/record.csv"

        with self.assertRaisesRegex(ValueError, "source_path path"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_expected_digest_must_be_sha256_prefixed_when_present(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = "abc123"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            observe_legacy_file_backed_locator(source, external_root=EXTERNAL_ROOT)

    def test_target_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            external_root = Path(temp_dir)
            target = external_root / "session-0001" / "record-0001 - measurement.csv"
            target.parent.mkdir(parents=True)
            target.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                observe_legacy_file_backed_locator(source, external_root=external_root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.csv").exists())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            external_root = Path(temp_dir)
            outside = external_root / "outside"
            outside.mkdir()
            (external_root / "session-0001").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                observe_legacy_file_backed_locator(source, external_root=external_root)

            self.assertTrue((external_root / "session-0001").is_symlink())

    def test_boundary_output_keeps_import_repair_and_preview_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-locator-observation-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("file-level observation", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["observation_effects"]["legacy_import_acceptance"], "not_performed"
        )
        self.assertEqual(candidate["observation_effects"]["reference_repair"], "not_performed")
        self.assertEqual(
            candidate["declared_preview_assertion"]["does_not_claim"],
            "previewability_or_schema_validation",
        )
        self.assertEqual(
            attention["file_level_locator_observation_only"]["does_not_claim"],
            "row_count_schema_preview_or_data_validation",
        )
        self.assertIn(
            "reference repair or moved-reference discovery", expected["decisions_not_earned"]
        )


if __name__ == "__main__":
    unittest.main()
