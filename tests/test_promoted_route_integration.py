from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.experiment_code import (
    EditableFolderObservationRequest,
    ManagedCodeVersionRequest,
    observe_editable_folder,
    summarize_managed_code_version,
)
from scopecat.handoff import (
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    run_handoff_durable_import_from_plan,
)
from scopecat.handoff.import_plan import HandoffImportPlanRequest, build_import_plan
from scopecat.handoff.receiving import (
    HandoffReceivingReviewRequest,
    run_receiving_gate_from_request,
)
from scopecat.measurement_records import (
    MeasurementRecordOperatorReviewRequest,
    review_measurement_records_from_request,
)
from scopecat.parameter_state import (
    build_prepared_run_source_agnostic_parameter_state_consumption_summary,
    build_prepared_run_source_agnostic_parameter_state_review_chain_summary,
)
from scopecat.prepared_run import (
    PreparedRunContextRequest,
    PreparedRunReviewGateRequest,
    compose_prepared_run_context,
    compose_prepared_run_review_gate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
HANDOFF_PACKAGE = (
    FIXTURES
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepared_run_context_source() -> dict:
    return _load(
        FIXTURES / "prepared_run_context" / "basic_preparation" / "prepared-run-context-input.json"
    )


def _context_by_family(source: dict, family: str) -> dict:
    matches = [record for record in source["context_records"] if record["family"] == family]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {family} context record")
    return matches[0]


def _receiving_request() -> HandoffReceivingReviewRequest:
    return HandoffReceivingReviewRequest(
        request_id="receive-handoff-package-legacy-rabi-001",
        reviewed_package_id="handoff-package-legacy-rabi-001",
        reviewed_preview_classification="needs_review_before_acceptance",
        reviewed_integrity_classification="declared_integrity_verified",
    )


def _import_plan_request() -> HandoffImportPlanRequest:
    return HandoffImportPlanRequest(
        request_id="plan-import-handoff-package-legacy-rabi-001",
        requested_package_id="handoff-package-legacy-rabi-001",
        measurement_selection="all_measurements",
    )


def _destination() -> HandoffDurableImportDestination:
    return HandoffDurableImportDestination(
        record_id="imported-legacy-rabi-001",
        record_dir="records/imported-legacy-rabi-001",
        primary_data_path="records/imported-legacy-rabi-001/primary.csv",
        writer_receipt_path="records/imported-legacy-rabi-001/writer-receipt.json",
        finalization_receipt_path="records/imported-legacy-rabi-001/finalization-receipt.json",
        read_model_path="records/imported-legacy-rabi-001/record-read-model.json",
    )


def _durable_import_request() -> HandoffDurableImportRequest:
    return HandoffDurableImportRequest(
        request_id="durably-import-handoff-package-legacy-rabi-001",
        approval_state="approved",
        requested_package_id="handoff-package-legacy-rabi-001",
        measurement_record_id="legacy-rabi-001",
        destination=_destination(),
    )


class PromotedRouteIntegrationTest(unittest.TestCase):
    def test_experiment_code_outputs_feed_prepared_run_context_by_declared_summary(self) -> None:
        managed_fixture = FIXTURES / "managed_code_version" / "basic_record"
        editable_fixture = FIXTURES / "editable_folder_observation" / "basic_observation"
        managed_summary = summarize_managed_code_version(
            ManagedCodeVersionRequest.from_dict(
                _load(managed_fixture / "managed-code-version-input.json")
            )
        ).to_dict()
        observation_summary = observe_editable_folder(
            EditableFolderObservationRequest.from_dict(
                _load(editable_fixture / "editable-folder-observation-input.json"),
                workspace_root=editable_fixture / "workspace",
            )
        ).to_dict()

        source = _prepared_run_context_source()
        managed_version = managed_summary["managed_code_versions"][0]
        managed_context = _context_by_family(source, "managed_code_version")
        managed_context["authority"] = "scopecat_experiment_code"
        managed_context["declared_summary"] = {
            "source_record_id": managed_version["source_record_id"],
            "stable_id": managed_version["stable_identity"]["stable_id"],
            "file_count": managed_version["file_count"],
            "materialization": "workspace_materialized",
        }

        observation = observation_summary["observation_requests"][0]
        editable_context = _context_by_family(source, "editable_workspace_observation")
        editable_context["authority"] = "scopecat_experiment_code"
        editable_context["declared_summary"] = {
            "selected_version_id": observation["selected_version_id"],
            "workspace_id": observation["workspace_id"],
            "root_label": observation["root_label"],
            "finding_counts": observation["finding_counts"],
        }

        result = compose_prepared_run_context(PreparedRunContextRequest.from_dict(source))
        prepared_summary = result.to_dict()

        selected_authority = {
            item["family"]: item.get("authority")
            for item in prepared_summary["selected_context_refs"]
            if item["family"] in {"managed_code_version", "editable_workspace_observation"}
        }
        self.assertEqual(
            selected_authority,
            {
                "managed_code_version": "scopecat_experiment_code",
                "editable_workspace_observation": "scopecat_experiment_code",
            },
        )
        self.assertIn(
            "workspace_observation_has_review_findings",
            {finding["finding"] for finding in prepared_summary["workspace_context_findings"]},
        )
        self.assertEqual(
            prepared_summary["prepared_run_context_policy"]["code_import_execution"],
            "not_performed",
        )

    def test_parameter_state_review_chain_feeds_prepared_run_review_gate(self) -> None:
        prepared_context = compose_prepared_run_context(
            PreparedRunContextRequest.from_dict(_prepared_run_context_source())
        ).to_dict()

        consumption_fixture = (
            FIXTURES
            / "prepared_run_source_agnostic_parameter_state_consumption"
            / "basic_consumption"
        )
        chain_fixture = (
            FIXTURES / "prepared_run_source_agnostic_parameter_state_review_chain" / "basic_chain"
        )
        consumption_summary = (
            build_prepared_run_source_agnostic_parameter_state_consumption_summary(
                _load(consumption_fixture / "consumption-input.json")
            )
        )
        chain_input = _load(chain_fixture / "review-chain-input.json")
        chain_input["source_agnostic_consumption_summary"] = consumption_summary
        chain_input["gate_input"]["parameter_state_consumption_summary"] = consumption_summary
        chain_input["scope_alignment_input"]["parameter_state_consumption_summary"] = (
            consumption_summary
        )
        parameter_chain = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(
            chain_input
        )

        gate_source = _load(
            FIXTURES / "prepared_run_review_gate" / "basic_gate" / "review-gate-input.json"
        )
        gate_source["review_gate_request"]["prepared_run_context_id"] = (
            "prepared-run-context-chevron-qA-0001"
        )
        gate_source["prepared_run_context_summary"] = prepared_context
        gate_source["parameter_state_gate_summary"] = parameter_chain["gate_summary"]
        gate_source["scope_alignment_summary"] = parameter_chain["scope_alignment_summary"]
        for bundle in gate_source["environment_review_summary"]["review_bundles"]:
            bundle["prepared_run_context_id"] = "prepared-run-context-chevron-qA-0001"

        gate = compose_prepared_run_review_gate(PreparedRunReviewGateRequest.from_dict(gate_source))
        gate_summary = gate.to_dict()

        self.assertEqual(gate.overall_state, "manual_pre_run_review_needed")
        self.assertIn(
            "parameter_state",
            {item["area"] for item in gate_summary["review_items"]},
        )
        self.assertIn(
            "scope_alignment",
            {finding["source_area"] for finding in gate_summary["aggregated_review_findings"]},
        )
        self.assertEqual(
            gate_summary["gate_decision"]["parameter_write_back"],
            "not_performed",
        )

    def test_handoff_durable_import_is_visible_to_measurement_record_operator_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / HANDOFF_PACKAGE.name
            storage_root = temp_root / "storage"
            shutil.copytree(HANDOFF_PACKAGE, package_dir)
            storage_root.mkdir()

            receiving_gate = run_receiving_gate_from_request(
                _receiving_request(),
                package_dir=package_dir,
            )
            import_plan = build_import_plan(
                _import_plan_request(),
                receiving_gate=receiving_gate,
            )
            import_run = run_handoff_durable_import_from_plan(
                _durable_import_request(),
                import_plan=import_plan,
                storage_root=storage_root,
            )
            review_run = review_measurement_records_from_request(
                MeasurementRecordOperatorReviewRequest(
                    request_id="review-imported-handoff-record",
                    selected_record_id="imported-legacy-rabi-001",
                ),
                storage_root=storage_root,
            )
            review_summary = review_run.to_dict()

        self.assertEqual(import_run.classification, "imported_handoff_measurement_record")
        self.assertEqual(review_run.classification, "measurement_record_operator_review_ready")
        self.assertEqual(review_summary["catalog"]["entry_count"], 1)
        self.assertEqual(review_summary["selected_record"]["source"], "catalog")
        self.assertEqual(
            review_summary["selected_record"]["record"]["record_id"],
            "imported-legacy-rabi-001",
        )
        self.assertEqual(
            review_summary["selected_record"]["record"]["lifecycle_state"],
            "complete",
        )
        self.assertEqual(review_summary["selected_record"]["review_finding_count"], 0)
        self.assertEqual(review_summary["next_action"], "review_selected_record_summary")


if __name__ == "__main__":
    unittest.main()
