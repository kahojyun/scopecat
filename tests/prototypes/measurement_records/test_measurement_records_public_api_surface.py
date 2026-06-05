from __future__ import annotations

import unittest

import scopecat.measurement_records as measurement_records


class MeasurementRecordsPublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in measurement_records.__all__:
            self.assertTrue(hasattr(measurement_records, name), name)

    def test_private_helpers_are_not_top_level_exports(self) -> None:
        private_names = {
            "READ_MODEL_SCHEMA",
            "_path_under",
            "_read_model",
            "_sha256",
            "_storage",
            "_validate_strict_child_path",
            "validate_public_identifier",
            "validate_relative_path",
        }
        private_symbols = private_names - {"_storage"}

        self.assertFalse(private_names.intersection(measurement_records.__all__))
        for name in private_symbols:
            self.assertFalse(hasattr(measurement_records, name), name)

    def test_caller_facing_capabilities_remain_top_level_exports(self) -> None:
        expected_names = {
            "ConvertedPrimaryData",
            "LegacyMeasurementRecordRequest",
            "LegacyMeasurementRecordRun",
            "LegacyMeasurementSource",
            "MeasurementRecordDurableImportRequest",
            "MeasurementRecordDurableImportRun",
            "MeasurementRecordImportSource",
            "MeasurementRecordReference",
            "MeasurementRecordReferenceRequest",
            "MeasurementRecordReferenceRun",
            "RecordedReferenceInput",
            "import_measurement_record_from_request",
            "list_measurement_record_references",
            "record_legacy_measurement",
            "record_legacy_measurement_from_request",
            "record_measurement_record_references_from_request",
        }

        self.assertEqual(set(measurement_records.__all__), expected_names)

    def test_slice_level_routes_are_not_top_level_exports(self) -> None:
        slice_names = {
            "MeasurementRecordCreationRequest",
            "MeasurementRecordExistingUpdateRequest",
            "MeasurementRecordFinalizationRequest",
            "MeasurementRecordInProgressUpdateRequest",
            "MeasurementRecordNormalizedPrimaryTableRequest",
            "MeasurementRecordReadModelRefreshRequest",
            "MeasurementRecordReadRequest",
            "MeasurementRecordRunningInspectionRequest",
            "MeasurementRecordWriterRequest",
            "append_existing_measurement_record_from_request",
            "append_in_progress_measurement_record_from_request",
            "attach_converted_primary_data_to_legacy_record_from_request",
            "create_measurement_record_from_request",
            "finalize_measurement_record_from_read_view",
            "inspect_running_measurement_record_from_request",
            "legacy_measurement_slug",
            "record_legacy_measurement_run_from_request",
            "refresh_measurement_record_read_model_from_read_view",
            "summarize_normalized_primary_table_from_request",
            "summarize_running_measurement_inspection",
            "write_created_record_primary_data_from_request",
        }

        self.assertFalse(slice_names.intersection(measurement_records.__all__))
        for name in slice_names:
            self.assertFalse(hasattr(measurement_records, name), name)


if __name__ == "__main__":
    unittest.main()
