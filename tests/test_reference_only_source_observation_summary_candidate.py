from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.reference_only_source_observation import (
    observe_reference_only_source,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reference_only_source_observation" / "basic_observation"
EXTERNAL_ROOT = FIXTURE / "external"


def _load_input() -> dict:
    return json.loads((FIXTURE / "source-observation-input.json").read_text(encoding="utf-8"))


class ReferenceOnlySourceObservationSummaryCandidateTest(unittest.TestCase):
    def test_observes_expected_external_source_without_data_claims(self) -> None:
        source = _load_input()

        summary = observe_reference_only_source(source, external_root=EXTERNAL_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-reference-only-source-observation-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)

    def test_input_is_not_mutated(self) -> None:
        source = _load_input()
        original = copy.deepcopy(source)

        observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(source, original)

    def test_unavailable_external_source_is_review_finding(self) -> None:
        source = _load_input()
        source["observation_request"]["source_path"] = "source-data/missing.csv"
        source["reference_only_import_facts"]["current_primary_data_reference"][
            "adapter_primary_data_path"
        ] = "source-data/missing.csv"

        summary = observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "external_source_unavailable_for_review",
        )
        self.assertEqual(summary["observed_external_source"]["status"], "unavailable")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["external_source_unavailable"],
        )

    def test_digest_and_size_mismatches_are_review_findings(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        source["observation_request"]["expected_size_bytes"] = 5

        summary = observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "external_source_observed_with_file_fact_mismatch",
        )
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["external_source_digest_mismatch", "external_source_size_mismatch"],
        )

    def test_rejects_data_observation_policy_claims(self) -> None:
        source = _load_input()
        source["source_observation_policy"]["data_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "data_observation"):
            observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

        source = _load_input()
        source["source_observation_policy"]["row_count"] = "performed"

        with self.assertRaisesRegex(ValueError, "row_count"):
            observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_observation_request_must_match_preserved_reference(self) -> None:
        cases = [
            ("reference_id", "other-reference", "reference_id"),
            ("external_root_label", "other-root", "external_root_label"),
            ("source_path", "source-data/other.csv", "source_path"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["observation_request"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_rejects_unapproved_or_inconsistent_reference_facts(self) -> None:
        cases = [
            (
                ("reference_only_request", "approval_state"),
                "rejected",
                "approved reference facts",
            ),
            (
                ("adapter_manifest_classification",),
                "adapter_manifest_blocked_for_review",
                "ready adapter manifest facts",
            ),
            (
                ("measurement_record", "classification"),
                "reference_only_import_blocked_for_review",
                "ready reference facts",
            ),
            (
                ("reference_only_request", "reviewed_manifest_classification"),
                "adapter_manifest_blocked_for_review",
                "reviewed classification",
            ),
            (
                ("reference_only_request", "materialization", "primary_data"),
                "copy_into_scopecat_storage",
                "reference-only materialization",
            ),
        ]
        for path, value, message in cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source["reference_only_import_facts"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, message):
                    observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_rejects_reference_facts_with_prior_observation(self) -> None:
        source = _load_input()
        source["reference_only_import_facts"]["current_primary_data_reference"]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with self.assertRaisesRegex(ValueError, "prior file observation"):
            observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_source_path_must_stay_relative(self) -> None:
        source = _load_input()
        source["observation_request"]["source_path"] = "../measurement.csv"
        source["reference_only_import_facts"]["current_primary_data_reference"][
            "adapter_primary_data_path"
        ] = "../measurement.csv"

        with self.assertRaisesRegex(ValueError, "source_path path"):
            observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_expected_digest_must_be_sha256_prefixed(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = "abc123"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            observe_reference_only_source(source, external_root=EXTERNAL_ROOT)

    def test_target_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            external_root = Path(temp_dir)
            target = external_root / "source-data" / "measurement.csv"
            target.parent.mkdir(parents=True)
            target.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                observe_reference_only_source(source, external_root=external_root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.csv").exists())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            external_root = Path(temp_dir)
            outside = external_root / "outside"
            outside.mkdir()
            (external_root / "source-data").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                observe_reference_only_source(source, external_root=external_root)

            self.assertTrue((external_root / "source-data").is_symlink())


if __name__ == "__main__":
    unittest.main()
