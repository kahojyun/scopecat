"""Caller-facing handoff package API.

Route-local result and projection objects remain importable from their owning
submodules without becoming package-root contracts.
"""

from scopecat.handoff.archive_materialization import (
    HandoffArchiveCreationRequest,
    HandoffArchiveMaterializationRequest,
    create_handoff_archive_package_from_request,
    materialize_handoff_archive_package_from_request,
)
from scopecat.handoff.durable_import import (
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    build_durable_import_request_from_handoff_plan,
    review_handoff_durable_import_retry,
    run_handoff_durable_import_from_plan,
    summarize_handoff_durable_import_receipt,
)
from scopecat.handoff.errors import HandoffContractError, HandoffError
from scopecat.handoff.import_plan import HandoffImportPlanRequest, build_import_plan
from scopecat.handoff.inspect import (
    HANDOFF_INSPECTION_ARTIFACT_NAME,
    build_inspection_html,
    write_inspection_artifact,
)
from scopecat.handoff.integrity import observe_package_integrity
from scopecat.handoff.package import summarize_package_context_references
from scopecat.handoff.read_only import open_package
from scopecat.handoff.receiving import (
    HandoffReceivingReviewRequest,
    run_receiving_gate_from_request,
)
from scopecat.handoff.selected_record_export import (
    SelectedMeasurementRecordBatchExportRecord,
    SelectedMeasurementRecordBatchExportRequest,
    SelectedMeasurementRecordExportLinkedContext,
    SelectedMeasurementRecordExportRequest,
    export_selected_measurement_record_batch_from_request,
    export_selected_measurement_record_from_request,
    export_selected_measurement_record_with_preflight_refresh,
)
from scopecat.handoff.workflow import run_package_workflow
from scopecat.handoff.writer import write_package

__all__ = [
    "HANDOFF_INSPECTION_ARTIFACT_NAME",
    "HandoffArchiveCreationRequest",
    "HandoffArchiveMaterializationRequest",
    "HandoffContractError",
    "HandoffDurableImportDestination",
    "HandoffDurableImportRequest",
    "HandoffError",
    "HandoffImportPlanRequest",
    "HandoffReceivingReviewRequest",
    "SelectedMeasurementRecordBatchExportRecord",
    "SelectedMeasurementRecordBatchExportRequest",
    "SelectedMeasurementRecordExportLinkedContext",
    "SelectedMeasurementRecordExportRequest",
    "build_durable_import_request_from_handoff_plan",
    "build_import_plan",
    "build_inspection_html",
    "create_handoff_archive_package_from_request",
    "export_selected_measurement_record_batch_from_request",
    "export_selected_measurement_record_from_request",
    "export_selected_measurement_record_with_preflight_refresh",
    "materialize_handoff_archive_package_from_request",
    "observe_package_integrity",
    "open_package",
    "review_handoff_durable_import_retry",
    "run_handoff_durable_import_from_plan",
    "run_package_workflow",
    "run_receiving_gate_from_request",
    "summarize_handoff_durable_import_receipt",
    "summarize_package_context_references",
    "write_inspection_artifact",
    "write_package",
]
