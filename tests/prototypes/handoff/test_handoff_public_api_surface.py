from __future__ import annotations

import importlib.util
import unittest

import scopecat.handoff as handoff


class HandoffPublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in handoff.__all__:
            self.assertTrue(hasattr(handoff, name), name)

    def test_candidate_storage_helpers_are_not_top_level_exports(self) -> None:
        legacy_names = {
            "HandoffApprovedImportDecision",
            "HandoffAcceptancePreflightRequest",
            "HandoffImportWorkflowRun",
            "HandoffNeedsReviewImportDecision",
            "HandoffRejectedImportDecision",
            "HandoffStorageAcceptanceRequest",
            "approve_import",
            "mark_import_needs_review",
            "reject_import",
            "review_import_workflow_retry",
            "run_acceptance_preflight",
            "run_import_workflow",
            "run_storage_acceptance",
            "summarize_import_workflow_receipt",
        }

        self.assertFalse(legacy_names.intersection(handoff.__all__))
        for name in legacy_names:
            self.assertFalse(hasattr(handoff, name), name)

    def test_candidate_storage_modules_are_retired_from_installable_src(self) -> None:
        retired_modules = {
            "scopecat.handoff.acceptance_preflight",
            "scopecat.handoff.import_workflow",
            "scopecat.handoff.storage_acceptance",
        }

        for module_name in retired_modules:
            self.assertIsNone(importlib.util.find_spec(module_name), module_name)

    def test_durable_handoff_import_remains_top_level_export(self) -> None:
        self.assertIn("run_handoff_durable_import", handoff.__all__)
        self.assertTrue(hasattr(handoff, "run_handoff_durable_import"))
        self.assertIn("summarize_handoff_durable_import_receipt", handoff.__all__)

    def test_context_reference_summary_is_top_level_export(self) -> None:
        self.assertIn("summarize_package_context_references", handoff.__all__)
        self.assertTrue(hasattr(handoff, "summarize_package_context_references"))

    def test_archive_materialization_is_top_level_export(self) -> None:
        self.assertIn("HandoffArchiveCreationRequest", handoff.__all__)
        self.assertIn("HandoffArchiveMaterializationRequest", handoff.__all__)
        self.assertIn("create_handoff_archive_package_from_request", handoff.__all__)
        self.assertIn("materialize_handoff_archive_package_from_request", handoff.__all__)
        self.assertTrue(hasattr(handoff, "create_handoff_archive_package_from_request"))
        self.assertTrue(hasattr(handoff, "materialize_handoff_archive_package_from_request"))

    def test_selected_record_preflight_export_is_top_level_export(self) -> None:
        self.assertIn("export_selected_measurement_record_with_preflight_refresh", handoff.__all__)
        self.assertTrue(
            hasattr(handoff, "export_selected_measurement_record_with_preflight_refresh")
        )

    def test_route_local_result_and_projection_types_are_not_top_level_exports(self) -> None:
        route_local_types = {
            "ArchiveMaterializationContractReview",
            "ArchiveMaterializationMemberReview",
            "HandoffArchiveCreationRun",
            "HandoffArchiveMaterializationRun",
            "HandoffContextReferenceSummary",
            "HandoffDurableImportReceiptSummary",
            "HandoffDurableImportRetryReview",
            "HandoffDurableImportRun",
            "HandoffErrorDiagnostic",
            "HandoffImportPlanRun",
            "HandoffIntegrityMemberObservation",
            "HandoffIntegrityOwnerRef",
            "HandoffJny001OperatorSmokeSummary",
            "HandoffLinkedContext",
            "HandoffLinkedContextImportPlan",
            "HandoffMeasurement",
            "HandoffMeasurementImportPlan",
            "HandoffPackage",
            "HandoffPackageIntegrityReport",
            "HandoffPackageWorkflowRun",
            "HandoffPackageWriteReceipt",
            "HandoffPlotSeries",
            "HandoffReceivingGateRun",
            "HandoffTable",
            "SelectedMeasurementRecordBatchExportRun",
            "SelectedMeasurementRecordExportRun",
            "SelectedMeasurementRecordPreflightExportRun",
        }

        self.assertFalse(route_local_types.intersection(handoff.__all__))
        for name in route_local_types:
            self.assertFalse(hasattr(handoff, name), name)


if __name__ == "__main__":
    unittest.main()
