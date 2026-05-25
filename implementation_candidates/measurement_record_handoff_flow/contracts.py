"""Candidate-local contract checks for measurement-record handoff flow.

The handoff flow still accepts JSON-shaped fixture input. This module is the
candidate-local boundary that turns those raw facts into a validated contract
before summary code adapts them into other slice-local inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts as _relative_parts,
)
from implementation_candidates.contract_primitives import (
    validate_positive_integer as _validate_positive_int,
)
from implementation_candidates.contract_primitives import (
    validate_public_identifier as _validate_public_identifier,
)
from implementation_candidates.contract_primitives import (
    validate_relative_path as _validate_relative_path,
)
from implementation_candidates.contract_primitives import (
    validate_sha256_digest,
)
from implementation_candidates.contract_primitives import (
    validate_strict_child_path as _validate_strict_child_path,
)
from implementation_candidates.contract_primitives import (
    validate_text as _validate_text,
)

_EXPECTED_POLICY = {
    "flow_authority": "explicit_measurement_record_handoff_flow_request",
    "slice_composition": "selected_explicit_candidate_facts",
    "legacy_import_acceptance": "consumed_as_explicit_accepted_record_facts",
    "source_observation": "performed_by_measurement_source_observation_candidate",
    "selected_export_summary": "performed_by_selected_measurement_export_candidate",
    "handoff_package_preview": "performed_by_handoff_package_contents_preview_candidate",
    "storage_mutation": "not_performed",
    "package_writing": "not_performed",
    "package_acceptance": "not_performed",
    "shared_measurement_schema": "not_defined",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
}

_EXPECTED_MATERIALIZATION = {
    "primary_data": "copy_into_storage",
    "linked_context": "reference_only",
    "source_identity": "preserve_external_reference",
}
_EXPECTED_PACKAGE_PRIMARY_DATA = {
    "kind": "primary_data",
    "label": "Accepted primary data",
    "include_status": "included_by_default",
    "relation": "selected_measurement_source",
    "authority": "scopecat_export_manifest",
    "format": "csv_table",
    "package_state": "packaged",
    "reason": None,
}
_EXPECTED_DEFAULT_PRIMARY_DATA = {
    "kind": "primary_data",
    "label": "Accepted primary data",
    "include_status": "included_by_default",
    "relation": "selected_measurement_source",
    "authority": "scopecat_export_manifest",
    "package_state": "packaged",
    "reason": None,
}
_WRITE_RESULT_PATH_FIELDS = {
    "primary_data": "primary_data_path",
    "imported_record_manifest": "manifest_path",
}
_EXPECTED_WRITE_RESULT_DOES_NOT_CLAIM = {
    "primary_data": "schema_or_scientific_validity",
    "imported_record_manifest": "final_storage_schema_or_package_integrity",
}
_REFERENCE_ONLY_CONTEXT_ERROR = (
    "handoff package linked context must match accepted reference-only context"
)
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private"))


@dataclass(frozen=True)
class AdapterReferenceText:
    """Adapter-declared scalar text, not a Scopecat-managed path."""

    value: str

    @classmethod
    def parse(cls, value: Any, owner: str) -> "AdapterReferenceText":
        _validate_text(value, owner)
        if not value.strip():
            raise ValueError(f"{owner} must be non-empty text")
        return cls(value=value)

    def to_summary(self) -> str:
        return self.value


@dataclass(frozen=True)
class LinkedContextExportPath:
    """Scopecat-managed linked-context reference path in export summaries."""

    value: str

    @classmethod
    def parse(cls, value: Any, owner: str) -> "LinkedContextExportPath":
        _validate_relative_path(value, owner)
        _validate_strict_child_path(value, "context", owner)
        return cls(value=value)

    def to_summary(self) -> str:
        return self.value


@dataclass(frozen=True)
class PackagePrimaryDataPath:
    """Scopecat-managed package path for the selected measurement data."""

    value: str

    @classmethod
    def parse(cls, value: Any, *, measurement_record_id: str) -> "PackagePrimaryDataPath":
        _validate_relative_path(value, "handoff package primary_data")
        _validate_strict_child_path(
            value,
            f"measurements/{measurement_record_id}",
            "handoff package primary_data",
        )
        return cls(value=value)

    def to_child_input(self) -> str:
        return self.value


@dataclass(frozen=True)
class PackageLinkedMeasurementIds:
    """Exact package-link backreference to the selected measurement."""

    values: tuple[str, ...]

    @classmethod
    def parse(
        cls,
        value: Any,
        *,
        measurement_record_id: str,
    ) -> "PackageLinkedMeasurementIds":
        if not isinstance(value, list):
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        linked_ids = tuple(value)
        if linked_ids != (measurement_record_id,):
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        return cls(values=linked_ids)

    def to_child_input(self) -> list[str]:
        return list(self.values)


@dataclass(frozen=True)
class PackageDeclaredExportSummaryId:
    """Package-declared source export summary label, not a continuity key."""

    value: str

    @classmethod
    def parse(cls, value: Any) -> "PackageDeclaredExportSummaryId":
        _validate_public_identifier(value, "handoff package source_export_summary_id")
        return cls(value=value)

    def to_child_input(self) -> str:
        return self.value


@dataclass(frozen=True)
class StoragePrimaryDataDisplayRef:
    """Redacted display ref derived from the accepted storage primary data path."""

    value: str

    @classmethod
    def parse(cls, value: Any, owner: str) -> "StoragePrimaryDataDisplayRef":
        _validate_redacted_display_ref(value, owner, prefix="SCOPECAT_STORAGE:")
        return cls(value=value)

    @classmethod
    def for_primary_data_path(cls, primary_data_path: str) -> "StoragePrimaryDataDisplayRef":
        return cls(value=f"SCOPECAT_STORAGE:/redacted/{primary_data_path}")

    def matches_primary_data_path(self, primary_data_path: str) -> bool:
        return self == self.for_primary_data_path(primary_data_path)

    def to_summary(self) -> str:
        return self.value


@dataclass(frozen=True)
class PreviewColumn:
    name: str
    role: str
    label: str
    unit: str

    @classmethod
    def parse(cls, value: dict[str, Any], owner: str) -> "PreviewColumn":
        _validate_public_identifier(value["name"], f"{owner} name")
        _validate_public_identifier(value["role"], f"{owner} role")
        _validate_text(value["label"], f"{owner} label")
        _validate_text(value["unit"], f"{owner} unit")
        return cls(
            name=value["name"],
            role=value["role"],
            label=value["label"],
            unit=value["unit"],
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "label": self.label,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class WriteResult:
    path: str
    kind: str
    result: str
    bytes_written: int
    digest: str
    does_not_claim: str

    @classmethod
    def parse(
        cls,
        value: dict[str, Any],
        *,
        expected_path: str,
    ) -> "WriteResult":
        kind = value["kind"]
        if value["result"] != "written":
            raise ValueError("accepted write result must be written")
        if value["path"] != expected_path:
            raise ValueError("accepted write result path must match acceptance request")
        _validate_relative_path(value["path"], f"accepted {kind} write")
        validate_sha256_digest(value["digest"], "accepted write result digest")
        _validate_positive_int(value["bytes_written"], "accepted write result bytes_written")
        if value["does_not_claim"] != _EXPECTED_WRITE_RESULT_DOES_NOT_CLAIM[kind]:
            raise ValueError(f"accepted {kind} write result does_not_claim must match contract")
        return cls(
            path=value["path"],
            kind=kind,
            result=value["result"],
            bytes_written=value["bytes_written"],
            digest=value["digest"],
            does_not_claim=value["does_not_claim"],
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "result": self.result,
            "bytes_written": self.bytes_written,
            "digest": self.digest,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True)
class PackageIdentity:
    package_id: str
    display_name: str
    created_by: str
    source_export_summary_id: PackageDeclaredExportSummaryId
    display_path: str
    local_path_redacted: bool

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "PackageIdentity":
        _validate_public_identifier(value["package_id"], "handoff package package_id")
        _validate_text(value["display_name"], "handoff package display_name")
        if value["created_by"] != "scopecat_selected_measurement_export":
            raise ValueError(
                "handoff package created_by must be scopecat_selected_measurement_export"
            )
        source_export_summary_id = PackageDeclaredExportSummaryId.parse(
            value["source_export_summary_id"]
        )
        _validate_redacted_display_ref(
            value["display_path"],
            "handoff package display_path",
            prefix="HANDOFF_PACKAGE:",
        )
        if value["local_path_redacted"] is not True:
            raise ValueError("handoff package local path must stay redacted")
        return cls(
            package_id=value["package_id"],
            display_name=value["display_name"],
            created_by=value["created_by"],
            source_export_summary_id=source_export_summary_id,
            display_path=value["display_path"],
            local_path_redacted=value["local_path_redacted"],
        )

    def to_child_input(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "display_name": self.display_name,
            "created_by": self.created_by,
            "source_export_summary_id": self.source_export_summary_id.to_child_input(),
            "display_path": self.display_path,
            "local_path_redacted": self.local_path_redacted,
        }


@dataclass(frozen=True)
class PackagePrimaryData:
    package_path: PackagePrimaryDataPath

    @classmethod
    def parse(cls, value: dict[str, Any], *, measurement_record_id: str) -> "PackagePrimaryData":
        for key, expected in _EXPECTED_PACKAGE_PRIMARY_DATA.items():
            if value[key] != expected:
                raise ValueError(f"handoff package primary_data {key} must be {expected}")
        package_path = PackagePrimaryDataPath.parse(
            value["package_path"],
            measurement_record_id=measurement_record_id,
        )
        return cls(package_path=package_path)

    def to_child_input(self) -> dict[str, Any]:
        return {
            "kind": "primary_data",
            "label": "Accepted primary data",
            "package_path": self.package_path.to_child_input(),
            "include_status": "included_by_default",
            "relation": "selected_measurement_source",
            "authority": "scopecat_export_manifest",
            "format": "csv_table",
            "package_state": "packaged",
            "reason": None,
        }


@dataclass(frozen=True)
class PackageBundleItem:
    item_id: str
    package_path: PackagePrimaryDataPath

    @classmethod
    def parse(
        cls,
        value: dict[str, Any],
        *,
        measurement_record_id: str,
        primary_data: PackagePrimaryData,
    ) -> "PackageBundleItem":
        for key, expected in _EXPECTED_DEFAULT_PRIMARY_DATA.items():
            if value[key] != expected:
                raise ValueError(
                    f"handoff package default bundle primary_data {key} must be {expected}"
                )
        if value["item_id"] != f"{measurement_record_id}-primary":
            raise ValueError(
                "handoff package default bundle primary item_id must match measurement"
            )
        if value["package_path"] != primary_data.package_path.to_child_input():
            raise ValueError("handoff package default bundle primary path must match primary data")
        return cls(item_id=value["item_id"], package_path=primary_data.package_path)

    def to_child_input(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": "primary_data",
            "label": "Accepted primary data",
            "package_path": self.package_path.to_child_input(),
            "include_status": "included_by_default",
            "relation": "selected_measurement_source",
            "authority": "scopecat_export_manifest",
            "package_state": "packaged",
            "reason": None,
        }


@dataclass(frozen=True)
class FlowRequest:
    flow_id: str
    legacy_data_id: int
    target: str
    source_observation_request_id: str
    export_source_display: StoragePrimaryDataDisplayRef

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "FlowRequest":
        _validate_public_identifier(value["flow_id"], "flow request flow_id")
        _validate_positive_int(value["legacy_data_id"], "flow request legacy_data_id")
        _validate_public_identifier(value["target"], "flow request target")
        _validate_public_identifier(
            value["source_observation_request_id"],
            "flow request source_observation_request_id",
        )
        export_source_display = StoragePrimaryDataDisplayRef.parse(
            value["export_source_display"],
            "flow request export_source_display",
        )
        return cls(
            flow_id=value["flow_id"],
            legacy_data_id=value["legacy_data_id"],
            target=value["target"],
            source_observation_request_id=value["source_observation_request_id"],
            export_source_display=export_source_display,
        )


@dataclass(frozen=True)
class MeasurementRecord:
    measurement_record_id: str
    label: str
    experiment_type: str
    source_kind: str
    classification: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "MeasurementRecord":
        _validate_public_identifier(value["measurement_record_id"], "measurement_record_id")
        _validate_text(value["label"], "measurement record label")
        _validate_public_identifier(value["experiment_type"], "measurement record experiment_type")
        if value["source_kind"] != "adapter_authored_legacy_import":
            raise ValueError("accepted record source_kind must be adapter_authored_legacy_import")
        if value["classification"] != "imported_ready_for_review":
            raise ValueError("accepted record classification must be imported_ready_for_review")
        return cls(
            measurement_record_id=value["measurement_record_id"],
            label=value["label"],
            experiment_type=value["experiment_type"],
            source_kind=value["source_kind"],
            classification=value["classification"],
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "measurement_record_id": self.measurement_record_id,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "source_kind": self.source_kind,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class SourceIdentity:
    external_record_id: str
    external_root_label: str
    original_path_display: str
    local_path_redacted: bool

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "SourceIdentity":
        _validate_public_identifier(
            value["external_record_id"],
            "accepted source identity external_record_id",
        )
        _validate_redacted_public_label(
            value["external_root_label"],
            "accepted source identity external_root_label",
        )
        if value["local_path_redacted"] is not True:
            raise ValueError("accepted source identity local path must stay redacted")
        _validate_redacted_display_ref(
            value["original_path_display"],
            "accepted source identity original_path_display",
            prefix="LEGACY_SOURCE:",
        )
        return cls(
            external_record_id=value["external_record_id"],
            external_root_label=value["external_root_label"],
            original_path_display=value["original_path_display"],
            local_path_redacted=value["local_path_redacted"],
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "external_record_id": self.external_record_id,
            "external_root_label": self.external_root_label,
            "original_path_display": self.original_path_display,
            "local_path_redacted": self.local_path_redacted,
        }


@dataclass(frozen=True)
class AcceptanceRequest:
    request_id: str
    approval_state: str
    reviewed_manifest_classification: str
    record_dir: str
    primary_data_path: str
    manifest_path: str
    collision_policy: str
    materialization: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "AcceptanceRequest":
        if value["approval_state"] != "approved":
            raise ValueError("accepted record approval_state must be approved")
        if value["reviewed_manifest_classification"] != "adapter_manifest_ready_for_review":
            raise ValueError("accepted record reviewed manifest must be ready")
        if value["collision_policy"] != "no_overwrite":
            raise ValueError("accepted record collision_policy must be no_overwrite")
        if value["materialization"] != _EXPECTED_MATERIALIZATION:
            raise ValueError("accepted record materialization must match handoff flow boundary")
        _validate_public_identifier(value["request_id"], "accepted request_id")
        _validate_storage_paths(value)
        return cls(
            request_id=value["request_id"],
            approval_state=value["approval_state"],
            reviewed_manifest_classification=value["reviewed_manifest_classification"],
            record_dir=value["record_dir"],
            primary_data_path=value["primary_data_path"],
            manifest_path=value["manifest_path"],
            collision_policy=value["collision_policy"],
            materialization=dict(value["materialization"]),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "reviewed_manifest_classification": self.reviewed_manifest_classification,
            "record_dir": self.record_dir,
            "primary_data_path": self.primary_data_path,
            "manifest_path": self.manifest_path,
            "collision_policy": self.collision_policy,
            "materialization": dict(self.materialization),
        }


@dataclass(frozen=True)
class AcceptedLinkedContext:
    link_id: str
    kind: str
    role: str
    label: str
    reference: AdapterReferenceText
    authority: str
    reference_state: str
    reason: None

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "AcceptedLinkedContext":
        link_id = value["link_id"]
        _validate_public_identifier(link_id, "accepted linked context link_id")
        _validate_public_identifier(value["kind"], f"accepted linked context {link_id} kind")
        _validate_public_identifier(value["role"], f"accepted linked context {link_id} role")
        _validate_text(value["label"], f"accepted linked context {link_id} label")
        if value["authority"] != "adapter_declared":
            raise ValueError(
                f"accepted linked context {link_id} authority must stay adapter_declared"
            )
        reference = AdapterReferenceText.parse(
            value["reference"],
            f"accepted linked context {link_id} reference",
        )
        if value["reference_state"] != "adapter_declared_available":
            raise ValueError(
                f"accepted linked context {link_id} must be adapter_declared_available"
            )
        if value["reason"] is not None:
            raise ValueError(
                f"accepted linked context {link_id} available reference must not carry reason"
            )
        return cls(
            link_id=link_id,
            kind=value["kind"],
            role=value["role"],
            label=value["label"],
            reference=reference,
            authority=value["authority"],
            reference_state=value["reference_state"],
            reason=None,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "kind": self.kind,
            "role": self.role,
            "label": self.label,
            "reference": self.reference.to_summary(),
            "authority": self.authority,
            "reference_state": self.reference_state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LinkedContextExportRef:
    source_link_id: str
    path: LinkedContextExportPath
    include_status: str
    relation: str
    authority: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "LinkedContextExportRef":
        link_id = value["source_link_id"]
        _validate_public_identifier(link_id, "linked context export ref source_link_id")
        path = LinkedContextExportPath.parse(
            value["path"],
            f"linked context export ref {link_id}",
        )
        _validate_public_identifier(
            value["relation"], f"linked context export ref {link_id} relation"
        )
        if value["authority"] != "adapter_declared":
            raise ValueError(
                f"linked context export ref {link_id} authority must stay adapter_declared"
            )
        if value["include_status"] != "visible_excluded":
            raise ValueError(
                f"linked context export ref {link_id} include_status must remain visible_excluded"
            )
        return cls(
            source_link_id=link_id,
            path=path,
            include_status=value["include_status"],
            relation=value["relation"],
            authority=value["authority"],
        )


@dataclass(frozen=True)
class PackageLinkedContext:
    link_id: str
    kind: str
    label: str
    package_path: None
    include_status: str
    relation: str
    authority: str
    package_state: str
    reason: str
    linked_measurement_record_ids: PackageLinkedMeasurementIds

    @classmethod
    def parse(
        cls,
        value: dict[str, Any],
        *,
        accepted: AcceptedLinkedContext,
        export_ref: LinkedContextExportRef,
        measurement_record_id: str,
    ) -> "PackageLinkedContext":
        expected_link_id = f"package-{accepted.link_id}"
        if value["link_id"] != expected_link_id:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["kind"] != accepted.kind:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        _validate_text(value["label"], "handoff package linked context label")
        if value["label"] != accepted.label:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["package_path"] is not None:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["include_status"] != export_ref.include_status:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["relation"] != export_ref.relation:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["authority"] != "scopecat_export_manifest":
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        if value["package_state"] != "not_packaged_visible_reference":
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        _validate_text(value["reason"], "handoff package linked context reason")
        linked_ids = PackageLinkedMeasurementIds.parse(
            value["linked_measurement_record_ids"],
            measurement_record_id=measurement_record_id,
        )
        return cls(
            link_id=value["link_id"],
            kind=value["kind"],
            label=value["label"],
            package_path=None,
            include_status=value["include_status"],
            relation=value["relation"],
            authority=value["authority"],
            package_state=value["package_state"],
            reason=value["reason"],
            linked_measurement_record_ids=linked_ids,
        )

    def to_child_input(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "package_path": self.package_path,
            "include_status": self.include_status,
            "relation": self.relation,
            "authority": self.authority,
            "package_state": self.package_state,
            "reason": self.reason,
            "linked_measurement_record_ids": self.linked_measurement_record_ids.to_child_input(),
        }


@dataclass(frozen=True)
class HandoffFlowContract:
    flow_request: FlowRequest
    measurement_record: MeasurementRecord
    source_identity: SourceIdentity
    acceptance_request: AcceptanceRequest
    accepted_linked_context: tuple[AcceptedLinkedContext, ...]
    package_linked_context: tuple[PackageLinkedContext, ...]
    accepted_record: dict[str, Any]
    primary_write_result: WriteResult
    write_results_by_kind: dict[str, WriteResult]
    linked_context_export_refs_by_id: dict[str, LinkedContextExportRef]
    accepted_preview_columns: tuple[PreviewColumn, ...]
    package_preview_columns: tuple[PreviewColumn, ...]
    package_identity: PackageIdentity
    package_primary_data: PackagePrimaryData
    package_default_bundle_item: PackageBundleItem


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = _relative_parts(left)
    right_parts = _relative_parts(right)
    return (
        left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
    )


def _validate_redacted_display_ref(value: Any, owner: str, *, prefix: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or not value.startswith(prefix)
        or value.startswith(("/", "~"))
        or "\\" in value
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or any(marker in value for marker in _PRIVATE_PATH_MARKERS)
        or "redacted" not in value.lower()
    ):
        raise ValueError(f"{owner} must be a public-safe redacted display reference")


def _validate_redacted_public_label(value: Any, owner: str) -> None:
    _validate_public_identifier(value, owner)
    if "redacted" not in value.lower():
        raise ValueError(f"{owner} must be a redacted public-safe label")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["flow_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("measurement record handoff flow policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"measurement record handoff flow policy {key} must be {expected}")


def _validate_storage_paths(request: dict[str, Any]) -> None:
    for field in ("record_dir", "primary_data_path", "manifest_path"):
        _validate_relative_path(request[field], f"accepted {field}")
    _validate_strict_child_path(
        request["primary_data_path"],
        request["record_dir"],
        "accepted primary_data_path",
    )
    _validate_strict_child_path(
        request["manifest_path"],
        request["record_dir"],
        "accepted manifest_path",
    )
    if _paths_overlap(request["primary_data_path"], request["manifest_path"]):
        raise ValueError("accepted primary data and manifest paths must not overlap")


def _validate_write_results(accepted_record: dict[str, Any]) -> dict[str, WriteResult]:
    request = accepted_record["acceptance_request"]
    by_kind = {}
    for result in accepted_record["write_results"]:
        kind = result["kind"]
        if kind not in _WRITE_RESULT_PATH_FIELDS:
            raise ValueError(f"accepted write result has unsupported kind: {kind}")
        if kind in by_kind:
            raise ValueError(f"accepted write result has duplicate kind: {kind}")

        expected_path = request[_WRITE_RESULT_PATH_FIELDS[kind]]
        by_kind[kind] = WriteResult.parse(result, expected_path=expected_path)

    if set(by_kind) != set(_WRITE_RESULT_PATH_FIELDS):
        raise ValueError(
            "accepted legacy import summary must include primary data and manifest write results"
        )
    return by_kind


def _validate_accepted_source_identity(source_identity: dict[str, Any]) -> SourceIdentity:
    return SourceIdentity.parse(source_identity)


def _validate_accepted_preview(
    preview: dict[str, Any],
    *,
    primary_data_path: str,
) -> tuple[PreviewColumn, ...]:
    if preview["status"] != "preview_ready":
        raise ValueError("accepted preview status must be preview_ready")
    if preview["metadata_authority"] != "adapter_declared":
        raise ValueError("accepted preview metadata_authority must be adapter_declared")
    _validate_public_identifier(preview["shape_kind"], "accepted preview shape_kind")
    _validate_positive_int(preview["declared_row_count"], "accepted preview declared_row_count")
    if preview["warnings"] != []:
        raise ValueError("accepted preview_ready records must not carry warning payloads")

    declared_columns = tuple(
        PreviewColumn.parse(column, "accepted preview declared column")
        for column in preview["declared_roles"]
    )
    declared_names = [column.name for column in declared_columns]
    if not declared_names or len(set(declared_names)) != len(declared_names):
        raise ValueError("accepted preview declared columns must be present and unique")
    declared_name_set = set(declared_names)
    if not preview["axis_order"] or any(
        axis not in declared_name_set for axis in preview["axis_order"]
    ):
        raise ValueError("accepted preview axis order must reference declared columns")
    for candidate in preview["plot_candidates"]:
        _validate_relative_path(candidate["source"], "accepted preview plot candidate source")
        if candidate["source"] != primary_data_path:
            raise ValueError(
                "accepted preview plot candidate source must match accepted primary_data_path"
            )
        if candidate["x"] not in declared_name_set or candidate["y"] not in declared_name_set:
            raise ValueError("accepted preview plot candidate axes must reference declared columns")
    return declared_columns


def _validate_accepted_linked_context(
    accepted_record: dict[str, Any],
) -> tuple[AcceptedLinkedContext, ...]:
    seen_ids = set()
    output = []
    for item in accepted_record["linked_context"]:
        link_id = item["link_id"]
        if link_id in seen_ids:
            raise ValueError(f"duplicate accepted linked context id: {link_id}")
        seen_ids.add(link_id)
        output.append(AcceptedLinkedContext.parse(item))
    return tuple(output)


def _validate_accepted_record(
    accepted_record: dict[str, Any],
) -> tuple[
    MeasurementRecord,
    SourceIdentity,
    AcceptanceRequest,
    tuple[AcceptedLinkedContext, ...],
    dict[str, WriteResult],
    tuple[PreviewColumn, ...],
]:
    record = accepted_record["measurement_record"]
    request = accepted_record["acceptance_request"]
    measurement_record = MeasurementRecord.parse(record)
    source_identity = _validate_accepted_source_identity(accepted_record["source_identity"])
    acceptance_request = AcceptanceRequest.parse(request)
    accepted_preview_columns = _validate_accepted_preview(
        accepted_record["preview"],
        primary_data_path=acceptance_request.primary_data_path,
    )
    accepted_linked_context = _validate_accepted_linked_context(accepted_record)
    return (
        measurement_record,
        source_identity,
        acceptance_request,
        accepted_linked_context,
        _validate_write_results(accepted_record),
        accepted_preview_columns,
    )


def _validate_flow_request(source: dict[str, Any]) -> FlowRequest:
    return FlowRequest.parse(source["flow_request"])


def _validate_legacy_source_location(source: dict[str, Any]) -> str:
    location = source["legacy_source_location"]
    _validate_redacted_display_ref(
        location["display_path"],
        "legacy source display_path",
        prefix="LEGACY_SOURCE:",
    )
    if location["local_path_public_safe"] is not False:
        raise ValueError("legacy source local_path must be marked non-public-safe")
    return location["display_path"]


def _linked_context_export_refs(source: dict[str, Any]) -> dict[str, LinkedContextExportRef]:
    refs = source["linked_context_export_refs"]
    by_link_id = {}
    paths_by_value: dict[str, str] = {}
    for item in refs:
        link_id = item["source_link_id"]
        if link_id in by_link_id:
            raise ValueError(f"duplicate linked context export ref: {link_id}")
        ref = LinkedContextExportRef.parse(item)
        path_value = ref.path.to_summary()
        if path_value in paths_by_value:
            raise ValueError(f"duplicate linked context export path: {path_value}")
        for existing_path in paths_by_value:
            if _paths_overlap(path_value, existing_path):
                raise ValueError(f"overlapping linked context export path: {path_value}")
        paths_by_value[path_value] = link_id
        by_link_id[link_id] = ref
    return by_link_id


def _validate_package_identity(source: dict[str, Any]) -> PackageIdentity:
    return PackageIdentity.parse(source["handoff_package_manifest"]["package_identity"])


def _validate_linked_context_export_refs(
    source: dict[str, Any],
    accepted_linked_context: tuple[AcceptedLinkedContext, ...],
) -> dict[str, LinkedContextExportRef]:
    refs_by_link_id = _linked_context_export_refs(source)
    accepted_by_link_id = {item.link_id: item for item in accepted_linked_context}
    extra_link_ids = set(refs_by_link_id) - set(accepted_by_link_id)
    if extra_link_ids:
        raise ValueError(f"unexpected linked context export ref: {sorted(extra_link_ids)[0]}")

    for link_id, item in accepted_by_link_id.items():
        if link_id not in refs_by_link_id:
            raise ValueError(f"missing linked context export ref: {link_id}")
        export_ref = refs_by_link_id[link_id]
        if export_ref.relation != item.role:
            raise ValueError(f"linked context export ref {link_id} relation must match source role")
        if export_ref.authority != item.authority:
            raise ValueError(
                f"linked context export ref {link_id} authority must match source authority"
            )
    return refs_by_link_id


def _validate_package_primary_data(
    package_record: dict[str, Any],
) -> tuple[PackagePrimaryData, PackageBundleItem]:
    primary_data = package_record["primary_data"]
    primary_data_contract = PackagePrimaryData.parse(
        primary_data,
        measurement_record_id=package_record["measurement_record_id"],
    )

    bundle = package_record["default_bundle"]
    if len(bundle) != 1:
        raise ValueError("handoff package default_bundle must contain one primary data item")
    bundle_item = bundle[0]
    bundle_item_contract = PackageBundleItem.parse(
        bundle_item,
        measurement_record_id=package_record["measurement_record_id"],
        primary_data=primary_data_contract,
    )
    return primary_data_contract, bundle_item_contract


def _validate_package_manifest_alignment(
    source: dict[str, Any],
    flow_request: FlowRequest,
    measurement_record: MeasurementRecord,
    accepted_record: dict[str, Any],
    accepted_preview_columns: tuple[PreviewColumn, ...],
) -> tuple[tuple[PreviewColumn, ...], PackagePrimaryData, PackageBundleItem]:
    selected = source["handoff_package_manifest"]["selected_measurements"]
    if len(selected) != 1:
        raise ValueError("handoff flow currently requires one selected package measurement")
    package_record = selected[0]
    if package_record["measurement_record_id"] != measurement_record.measurement_record_id:
        raise ValueError(
            "handoff package manifest measurement_record_id must match accepted record"
        )
    if package_record["legacy_data_id"] != flow_request.legacy_data_id:
        raise ValueError("handoff package manifest legacy_data_id must match flow request")
    if package_record["label"] != measurement_record.label:
        raise ValueError("handoff package manifest label must match accepted record")
    if package_record["experiment_type"] != measurement_record.experiment_type:
        raise ValueError("handoff package manifest experiment_type must match accepted record")
    if package_record["target"] != flow_request.target:
        raise ValueError("handoff package manifest target must match flow request")
    primary_data, bundle_item = _validate_package_primary_data(package_record)

    accepted_preview = accepted_record["preview"]
    package_preview = package_record["declared_preview_metadata"]
    if package_preview["metadata_authority"] != "scopecat_export_manifest":
        raise ValueError(
            "handoff package manifest preview authority must be scopecat_export_manifest"
        )
    if package_preview["status"] != accepted_preview["status"]:
        raise ValueError("handoff package manifest preview status must match accepted record")
    if package_preview["data_shape"]["kind"] != accepted_preview["shape_kind"]:
        raise ValueError("handoff package manifest preview shape must match accepted record")
    if list(package_preview["data_shape"]["axis_order"]) != list(accepted_preview["axis_order"]):
        raise ValueError("handoff package manifest preview axis order must match accepted record")
    package_preview_columns = tuple(
        PreviewColumn.parse(column, "handoff package preview declared column")
        for column in package_preview["declared_columns"]
    )
    if package_preview_columns != accepted_preview_columns:
        raise ValueError("handoff package manifest preview columns must match accepted record")
    package_plot_axes = [
        {"x": candidate["x"], "y": candidate["y"]}
        for candidate in package_preview["plot_candidates"]
    ]
    accepted_plot_axes = [
        {"x": candidate["x"], "y": candidate["y"]}
        for candidate in accepted_preview["plot_candidates"]
    ]
    if package_plot_axes != accepted_plot_axes:
        raise ValueError("handoff package manifest preview plot axes must match accepted record")
    for candidate in package_preview["plot_candidates"]:
        if candidate["source"] != primary_data.package_path.to_child_input():
            raise ValueError("handoff package manifest preview plot source must match primary data")
    return package_preview_columns, primary_data, bundle_item


def _validate_linked_context_alignment(
    source: dict[str, Any],
    measurement_record: MeasurementRecord,
    accepted_linked_context: tuple[AcceptedLinkedContext, ...],
    refs_by_link_id: dict[str, LinkedContextExportRef],
) -> tuple[PackageLinkedContext, ...]:
    manifest_context = source["handoff_package_manifest"]["linked_context"]
    if len(manifest_context) != len(accepted_linked_context):
        raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
    package_by_source_id = {
        item["link_id"].removeprefix("package-"): item for item in manifest_context
    }
    output = []
    for accepted in accepted_linked_context:
        if accepted.link_id not in package_by_source_id:
            raise ValueError(_REFERENCE_ONLY_CONTEXT_ERROR)
        output.append(
            PackageLinkedContext.parse(
                package_by_source_id[accepted.link_id],
                accepted=accepted,
                export_ref=refs_by_link_id[accepted.link_id],
                measurement_record_id=measurement_record.measurement_record_id,
            )
        )
    return tuple(output)


def validate_measurement_record_handoff_flow_contract(
    source: dict[str, Any],
) -> HandoffFlowContract:
    """Validate raw handoff flow input before adapting it into composed slices."""
    _validate_policy(source)
    flow_request = _validate_flow_request(source)
    legacy_display_path = _validate_legacy_source_location(source)
    accepted_record = source["accepted_record"]
    (
        measurement_record,
        source_identity,
        acceptance_request,
        accepted_linked_context,
        write_results_by_kind,
        accepted_preview_columns,
    ) = _validate_accepted_record(accepted_record)
    if source_identity.original_path_display != legacy_display_path:
        raise ValueError(
            "accepted source identity original_path_display must match legacy source display_path"
        )
    if not flow_request.export_source_display.matches_primary_data_path(
        acceptance_request.primary_data_path
    ):
        raise ValueError("flow request export_source_display must match accepted primary_data_path")
    package_identity = _validate_package_identity(source)
    refs_by_link_id = _validate_linked_context_export_refs(source, accepted_linked_context)
    package_preview_columns, package_primary_data, package_default_bundle_item = (
        _validate_package_manifest_alignment(
            source,
            flow_request,
            measurement_record,
            accepted_record,
            accepted_preview_columns,
        )
    )
    package_linked_context = _validate_linked_context_alignment(
        source,
        measurement_record,
        accepted_linked_context,
        refs_by_link_id,
    )
    return HandoffFlowContract(
        flow_request=flow_request,
        measurement_record=measurement_record,
        source_identity=source_identity,
        acceptance_request=acceptance_request,
        accepted_linked_context=accepted_linked_context,
        package_linked_context=package_linked_context,
        accepted_record=accepted_record,
        primary_write_result=write_results_by_kind["primary_data"],
        write_results_by_kind=write_results_by_kind,
        linked_context_export_refs_by_id=refs_by_link_id,
        accepted_preview_columns=accepted_preview_columns,
        package_preview_columns=package_preview_columns,
        package_identity=package_identity,
        package_primary_data=package_primary_data,
        package_default_bundle_item=package_default_bundle_item,
    )
