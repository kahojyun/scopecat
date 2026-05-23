from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.measurement_source_observation import observe_measurement_source

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_source_observation" / "basic_observation"
STORAGE_ROOT = FIXTURE / "source"


def _load_input() -> dict:
    return json.loads((FIXTURE / "source-observation-input.json").read_text(encoding="utf-8"))


def _set_expected_file_facts(source: dict, path: Path) -> None:
    content = path.read_bytes()
    source["observation_request"]["expected_digest"] = (
        f"sha256:{hashlib.sha256(content).hexdigest()}"
    )
    source["observation_request"]["expected_size_bytes"] = len(content)


class MeasurementSourceObservationSummaryCandidateTest(unittest.TestCase):
    def test_observes_expected_primary_data_without_mutation(self) -> None:
        summary = observe_measurement_source(_load_input(), storage_root=STORAGE_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-source-observation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertEqual(
            (STORAGE_ROOT / "records" / "run-3101-rabi" / "primary.csv").read_text(
                encoding="utf-8"
            ),
            (
                "drive_amplitude,excited_state_probability\n"
                "0.00,0.02\n"
                "0.25,0.18\n"
                "0.50,0.51\n"
                "0.75,0.83\n"
                "1.00,0.94\n"
            ),
        )

    def test_attention_records_all_boundary_deferrals(self) -> None:
        summary = observe_measurement_source(_load_input(), storage_root=STORAGE_ROOT)

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            _load_input()["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["source_observation_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["source_observation_policy"]["schema_detection"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected measurement source observation"):
            observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_unavailable_primary_data_is_reported_as_review_finding(self) -> None:
        source = _load_input()
        source["observation_request"]["primary_data_path"] = "records/run-3101-rabi/missing.csv"
        source["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
            "records/run-3101-rabi/missing.csv"
        )

        summary = observe_measurement_source(source, storage_root=STORAGE_ROOT)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "source_unavailable_for_review",
        )
        self.assertEqual(summary["observed_primary_data"]["status"], "unavailable")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["primary_data_unavailable"],
        )

    def test_digest_mismatch_is_reported_without_repair(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        summary = observe_measurement_source(source, storage_root=STORAGE_ROOT)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "source_observed_with_mismatch",
        )
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["primary_data_digest_mismatch"],
        )
        self.assertEqual(
            summary["observed_primary_data"]["observed_digest"],
            "sha256:8b335f804ede7480a10b8ade2b2d95b12e1e741c9a0daa3d4257048346b3672b",
        )

    def test_size_and_row_count_mismatches_are_reported(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_size_bytes"] = 91
        source["observation_request"]["expected_rows_recorded"] = 4

        summary = observe_measurement_source(source, storage_root=STORAGE_ROOT)

        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["primary_data_size_mismatch", "primary_data_row_count_mismatch"],
        )

    def test_observed_path_must_stay_relative(self) -> None:
        source = _load_input()
        source["observation_request"]["primary_data_path"] = "../primary.csv"

        with self.assertRaisesRegex(ValueError, "primary_data_path path"):
            observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_expected_digest_must_be_sha256_prefixed(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = "8b335"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_expected_counts_must_be_strict_nonnegative_integers(self) -> None:
        cases = [
            ("expected_size_bytes", True, "expected_size_bytes"),
            ("expected_size_bytes", -1, "expected_size_bytes"),
            ("expected_rows_recorded", 5.0, "expected_rows_recorded"),
            ("expected_rows_recorded", -1, "expected_rows_recorded"),
        ]

        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["observation_request"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_target_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            target = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            target.parent.mkdir(parents=True)
            target.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                observe_measurement_source(source, storage_root=storage_root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.csv").exists())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            outside = storage_root / "outside"
            outside.mkdir()
            records = storage_root / "records"
            records.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                observe_measurement_source(source, storage_root=storage_root)

            self.assertTrue(records.is_symlink())

    def test_csv_row_count_handles_quoted_newline(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_rows_recorded"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            target = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            target.parent.mkdir(parents=True)
            target.write_text(
                ('drive_amplitude,excited_state_probability\n0.00,"0.02\ncontinued"\n0.25,0.18\n'),
                encoding="utf-8",
                newline="",
            )
            _set_expected_file_facts(source, target)

            summary = observe_measurement_source(source, storage_root=storage_root)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "source_observed_matches_declared_facts",
        )
        self.assertEqual(summary["observed_primary_data"]["observed_rows_recorded"], 2)

    def test_zero_row_primary_data_is_allowed(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_rows_recorded"] = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            target = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            target.parent.mkdir(parents=True)
            target.write_text(
                "drive_amplitude,excited_state_probability\n",
                encoding="utf-8",
                newline="",
            )
            _set_expected_file_facts(source, target)

            summary = observe_measurement_source(source, storage_root=storage_root)

        self.assertEqual(
            summary["measurement_record"]["classification"],
            "source_observed_matches_declared_facts",
        )
        self.assertEqual(summary["observed_primary_data"]["observed_rows_recorded"], 0)

    def test_preview_plot_candidate_must_reference_observed_primary_data(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
            "records/run-3101-rabi/wrong.csv"
        )

        with self.assertRaisesRegex(ValueError, "plot candidate source"):
            observe_measurement_source(source, storage_root=STORAGE_ROOT)

    def test_input_is_not_mutated(self) -> None:
        source = _load_input()
        original = copy.deepcopy(source)

        observe_measurement_source(source, storage_root=STORAGE_ROOT)

        self.assertEqual(source, original)


if __name__ == "__main__":
    unittest.main()
