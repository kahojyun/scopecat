from __future__ import annotations

import unittest

import scopecat.measurement_records as measurement_records


class MeasurementRecordsPublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in measurement_records.__all__:
            self.assertTrue(hasattr(measurement_records, name), name)

    def test_private_helpers_are_not_top_level_exports(self) -> None:
        private_names = {
            "DURABLE_IMPORT_POLICY",
            "READ_MODEL_PROJECTION_POLICY",
            "READ_MODEL_REFRESH_POLICY",
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

    def test_durable_import_and_read_model_routes_remain_top_level_exports(self) -> None:
        expected_names = {
            "MeasurementRecordDurableImportRequest",
            "MeasurementRecordExistingUpdateRequest",
            "MeasurementRecordReferenceRequest",
            "MeasurementRecordNormalizedPrimaryTableRequest",
            "MeasurementRecordReadModelProjectionRequest",
            "MeasurementRecordReadModelRefreshRequest",
            "MeasurementRecordStorageInventoryRequest",
            "MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME",
            "LegacyPrimaryImportRequest",
            "LegacyRunRecordRequest",
            "MeasurementRecordCatalogRequest",
            "attach_converted_primary_data_to_legacy_record_from_request",
            "record_measurement_record_references_from_request",
            "append_existing_measurement_record_from_request",
            "build_measurement_record_review_html",
            "import_measurement_record_from_request",
            "list_measurement_record_storage_from_request",
            "list_measurement_record_references",
            "project_measurement_record_read_model_from_read_view",
            "record_legacy_measurement_run_from_request",
            "refresh_measurement_record_read_model_from_read_view",
            "catalog_measurement_record_read_models_from_request",
            "summarize_normalized_primary_table_from_request",
            "write_measurement_record_review_artifact",
        }

        self.assertTrue(expected_names.issubset(measurement_records.__all__))


if __name__ == "__main__":
    unittest.main()
