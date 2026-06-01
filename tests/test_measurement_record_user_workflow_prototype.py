from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    ConvertedPrimaryData,
    LegacyMeasurementRecordRequest,
    LegacyMeasurementSource,
    RecordedReferenceInput,
    legacy_measurement_slug,
    record_legacy_measurement,
    record_legacy_measurement_from_request,
)


def _write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("time_s", "signal_counts"))
        writer.writeheader()
        writer.writerows(
            [
                {"time_s": "0.000", "signal_counts": "101"},
                {"time_s": "0.100", "signal_counts": "128"},
            ]
        )


def _source(**overrides: object) -> LegacyMeasurementSource:
    values = {
        "legacy_system_id": "legacy-labview",
        "legacy_run_id": "lv-run-001",
        "label": "Legacy LabVIEW Run 001",
        "experiment_type": "rabi",
        "primary_locator": "legacy-system/run-001.tsv",
        "notebook_locator": "legacy-notebook://operator-workstation/run-001",
        "created_at": "2026-06-01T09:00:00Z",
        "run_started_at": "2026-06-01T08:50:00Z",
        "run_completed_at": "2026-06-01T08:55:00Z",
    }
    values.update(overrides)
    return LegacyMeasurementSource(**values)


def _references() -> tuple[RecordedReferenceInput, ...]:
    return (
        RecordedReferenceInput(
            family="parameter_state",
            role="parameter_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/params/lv-run-001.json",
            label="Legacy parameter file",
        ),
        RecordedReferenceInput(
            family="derived_artifact",
            role="preliminary_analysis_result",
            reference_kind="workspace_relative_path",
            reference_value="analysis/lv-run-001/summary.csv",
            label="Initial analysis summary",
            preview="contrast=0.82",
        ),
    )


class MeasurementRecordUserWorkflowPrototypeTest(unittest.TestCase):
    def test_records_legacy_measurement_without_user_supplied_scopecat_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            primary_path = content_root / "normalized" / "lv-run-001.csv"
            _write_csv(primary_path)

            run = record_legacy_measurement(
                source=_source(),
                primary_data=ConvertedPrimaryData(path=primary_path, rows_recorded=2),
                references=_references(),
                storage_root=storage_root,
                content_root=content_root,
            )

        payload = run.to_dict()
        self.assertTrue(run.recorded)
        self.assertEqual(run.classification, "recorded_legacy_measurement")
        self.assertEqual(
            payload["generated_ids"]["record_id"],
            "rec-legacy-labview-lv-run-001",
        )
        self.assertEqual(
            payload["generated_ids"]["recorded_reference_set_id"],
            "references-legacy-labview-lv-run-001",
        )
        self.assertEqual(
            payload["legacy_run"]["workflow"]["classification"],
            "recorded_legacy_run",
        )
        self.assertEqual(
            payload["primary_attach"]["workflow"]["classification"],
            "attached_legacy_primary_data",
        )
        self.assertEqual(
            payload["recorded_reference"]["workflow"]["classification"],
            "recorded_measurement_record_references",
        )
        self.assertEqual(payload["read_view"]["workflow"]["classification"], "primary_table_ready")
        self.assertNotIn("record_id", payload["request"]["source"])

    def test_request_entrypoint_matches_direct_facade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            primary_path = content_root / "normalized" / "lv-run-001.csv"
            _write_csv(primary_path)
            request = LegacyMeasurementRecordRequest(
                source=_source(),
                primary_data=ConvertedPrimaryData(path=primary_path, rows_recorded=2),
                references=(),
            )

            run = record_legacy_measurement_from_request(
                request,
                storage_root=storage_root,
                content_root=content_root,
            )

        self.assertTrue(run.recorded)
        self.assertIsNone(run.recorded_reference)
        self.assertEqual(
            run.generated_ids.measurement_id,
            f"meas-{legacy_measurement_slug(_source())}",
        )

    def test_converted_primary_data_must_stay_under_content_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            outside_root = Path(temp_dir) / "outside"
            storage_root.mkdir()
            content_root.mkdir()
            primary_path = outside_root / "lv-run-001.csv"
            _write_csv(primary_path)

            with self.assertRaisesRegex(ValueError, "under content_root"):
                record_legacy_measurement(
                    source=_source(),
                    primary_data=ConvertedPrimaryData(path=primary_path, rows_recorded=2),
                    storage_root=storage_root,
                    content_root=content_root,
                )


if __name__ == "__main__":
    unittest.main()
