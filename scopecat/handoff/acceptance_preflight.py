"""Read-only acceptance preflight for handoff import plans."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    relative_path_parts,
    validate_public_identifier,
    validate_relative_path,
    validate_strict_child_path,
)
from scopecat.handoff.import_plan import HandoffImportPlanRun, run_import_plan

_EXPECTED_SCHEMA = "scopecat.handoff_acceptance_preflight.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "approved_acceptance_preflight_request",
    "import_plan": "required_ready_non_mutating_import_plan",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "destination_observation": "exact_declared_paths_only",
    "collision_policy": "no_overwrite",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "conflict_resolution": "not_performed",
    "rollback": "not_defined",
    "final_storage_schema": "not_defined",
}


@dataclass(frozen=True)
class HandoffAcceptanceDestination:
    """Declared destination paths for one planned measurement import."""

    measurement_record_id: str
    destination_record_id: str
    record_dir: str
    primary_data_path: str
    manifest_path: str
    storage_schema: str

    @property
    def target_paths(self) -> tuple[str, ...]:
        return (self.record_dir, self.primary_data_path, self.manifest_path)

    def to_dict(self) -> dict[str, str]:
        return {
            "measurement_record_id": self.measurement_record_id,
            "destination_record_id": self.destination_record_id,
            "record_dir": self.record_dir,
            "primary_data_path": self.primary_data_path,
            "manifest_path": self.manifest_path,
            "storage_schema": self.storage_schema,
        }


@dataclass(frozen=True)
class HandoffAcceptancePreflightRequest:
    """Approved request to check destinations before acceptance mutation."""

    request_id: str
    requested_package_id: str
    destinations: tuple[HandoffAcceptanceDestination, ...]

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return tuple(destination.measurement_record_id for destination in self.destinations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": "approved",
            "requested_package_id": self.requested_package_id,
            "destination_policy": {
                "path_kind": "relative_storage_path_under_caller_root",
                "collision_policy": "no_overwrite",
                "storage_schema": "declared_candidate_only",
            },
            "destinations": [destination.to_dict() for destination in self.destinations],
        }


@dataclass(frozen=True)
class HandoffDestinationObservation:
    """Read-only observation for one declared destination."""

    destination: HandoffAcceptanceDestination
    target_states: tuple[dict[str, str], ...]

    @property
    def has_collision(self) -> bool:
        return any(item["state"] == "exists" for item in self.target_states)

    @property
    def classification(self) -> str:
        if self.has_collision:
            return "destination_collision"
        return "destination_available"

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.destination.to_dict(),
            "classification": self.classification,
            "target_states": [copy.deepcopy(item) for item in self.target_states],
        }


@dataclass(frozen=True)
class HandoffAcceptancePreflightRun:
    """Read-only destination preflight for a ready import plan."""

    request: HandoffAcceptancePreflightRequest
    import_plan: HandoffImportPlanRun
    destination_observations: tuple[HandoffDestinationObservation, ...]

    @property
    def has_collision(self) -> bool:
        return any(observation.has_collision for observation in self.destination_observations)

    @property
    def acceptance_preflight_allowed(self) -> bool:
        return self.import_plan.import_plan_allowed and not self.has_collision

    @property
    def classification(self) -> str:
        if not self.import_plan.import_plan_allowed:
            return "blocked_before_acceptance_preflight"
        if self.has_collision:
            return "blocked_by_destination_collision"
        return "ready_for_acceptance_mutation_request"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_acceptance_preflight_receipt",
            "acceptance_preflight_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "run_import_plan",
                    "validate_declared_destinations",
                    "observe_declared_destination_paths",
                    "summarize_acceptance_preflight",
                ],
                "does_not_claim": [
                    "storage_mutation",
                    "package_import_or_acceptance",
                    "conflict_resolution",
                    "final_storage_schema",
                    "rollback_policy",
                    "manifest_write",
                ],
            },
            "request": self.request.to_dict(),
            "import_plan": {
                "classification": self.import_plan.classification,
                "allowed": self.import_plan.import_plan_allowed,
                "planned_measurement_ids": [
                    plan.measurement.measurement_record_id
                    for plan in self.import_plan.measurement_plans
                ],
            },
            "destination_observation": {
                "performed": self.import_plan.import_plan_allowed,
                "classification": (
                    "destination_collision"
                    if self.has_collision
                    else "declared_destinations_available"
                ),
                "observed_paths": [
                    observation.to_dict() for observation in self.destination_observations
                ],
            },
            "acceptance_preflight": {
                "allowed": self.acceptance_preflight_allowed,
                "next_required_decision": (
                    "approve_storage_mutation_with_conflict_and_rollback_policy"
                    if self.acceptance_preflight_allowed
                    else "resolve_import_plan_or_destination_collisions_before_mutation"
                ),
            },
        }


def run_acceptance_preflight(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffAcceptancePreflightRun:
    """Check declared acceptance destinations without writing storage records."""

    request, import_plan_source = _parse_source(source)
    import_plan = run_import_plan(import_plan_source, package_dir=package_dir)
    return build_acceptance_preflight(
        request,
        import_plan=import_plan,
        storage_root=storage_root,
    )


def build_acceptance_preflight(
    request: HandoffAcceptancePreflightRequest,
    *,
    import_plan: HandoffImportPlanRun,
    storage_root: str | Path,
) -> HandoffAcceptancePreflightRun:
    """Build an acceptance preflight from a typed import plan."""

    _validate_against_import_plan(request=request, import_plan=import_plan)

    destination_observations: tuple[HandoffDestinationObservation, ...] = ()
    if import_plan.import_plan_allowed:
        root = _existing_storage_root(Path(storage_root))
        destination_observations = tuple(
            _observe_destination(root, destination) for destination in request.destinations
        )

    return HandoffAcceptancePreflightRun(
        request=request,
        import_plan=import_plan,
        destination_observations=destination_observations,
    )


def _existing_storage_root(storage_root: Path) -> Path:
    if storage_root.is_symlink():
        raise ValueError("handoff acceptance storage root must not be a symlink")
    if not storage_root.is_dir():
        raise ValueError("handoff acceptance preflight requires an existing storage root")
    return storage_root.resolve()


def _target_state(storage_root: Path, relative_path: str) -> dict[str, str]:
    target = storage_root.joinpath(*relative_path_parts(relative_path, "acceptance target path"))
    return {
        "path": relative_path,
        "state": "exists" if target.exists() else "available",
    }


def _observe_destination(
    storage_root: Path,
    destination: HandoffAcceptanceDestination,
) -> HandoffDestinationObservation:
    return HandoffDestinationObservation(
        destination=destination,
        target_states=tuple(_target_state(storage_root, path) for path in destination.target_paths),
    )


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _parse_source(
    source: dict[str, Any],
) -> tuple[HandoffAcceptancePreflightRequest, dict[str, Any]]:
    source = _require_mapping(source, "handoff acceptance preflight source")
    _require_keys(
        source,
        {
            "acceptance_preflight_schema",
            "acceptance_preflight_policy",
            "import_plan_source",
            "acceptance_preflight_request",
        },
        "handoff acceptance preflight source",
    )
    if source["acceptance_preflight_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("acceptance_preflight_schema is unsupported")
    if source["acceptance_preflight_policy"] != _EXPECTED_POLICY:
        raise ValueError("acceptance_preflight_policy is unsupported")

    import_plan_source = _require_mapping(source["import_plan_source"], "import_plan_source")
    request = _parse_request(source["acceptance_preflight_request"])
    return request, copy.deepcopy(import_plan_source)


def _parse_request(source: Any) -> HandoffAcceptancePreflightRequest:
    request = _require_mapping(source, "acceptance_preflight_request")
    _require_keys(
        request,
        {
            "request_id",
            "approval_state",
            "requested_package_id",
            "destination_policy",
            "destinations",
        },
        "acceptance_preflight_request",
    )
    if request["approval_state"] != "approved":
        raise ValueError("handoff acceptance preflight requires approved request")
    _parse_destination_policy(request["destination_policy"])
    destinations = _parse_destinations(request["destinations"])
    return HandoffAcceptancePreflightRequest(
        request_id=validate_public_identifier(
            request["request_id"],
            "acceptance_preflight_request.request_id",
        ),
        requested_package_id=validate_public_identifier(
            request["requested_package_id"],
            "acceptance_preflight_request.requested_package_id",
        ),
        destinations=destinations,
    )


def _parse_destination_policy(source: Any) -> None:
    policy = _require_mapping(source, "acceptance_preflight_request.destination_policy")
    _require_keys(
        policy,
        {"path_kind", "collision_policy", "storage_schema"},
        "acceptance_preflight_request.destination_policy",
    )
    if policy["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("destination path_kind is unsupported")
    if policy["collision_policy"] != "no_overwrite":
        raise ValueError("destination collision_policy is unsupported")
    if policy["storage_schema"] != "declared_candidate_only":
        raise ValueError("destination storage_schema is unsupported")


def _parse_destinations(source: Any) -> tuple[HandoffAcceptanceDestination, ...]:
    if not isinstance(source, list):
        raise ValueError("acceptance destinations must be a list")
    destinations = tuple(_parse_destination(item) for item in source)
    if not destinations:
        raise ValueError("acceptance destinations must not be empty")
    measurement_ids = [item.measurement_record_id for item in destinations]
    if len(set(measurement_ids)) != len(measurement_ids):
        raise ValueError("acceptance destination measurement ids must be unique")
    destination_record_ids = [item.destination_record_id for item in destinations]
    if len(set(destination_record_ids)) != len(destination_record_ids):
        raise ValueError("acceptance destination record ids must be unique")
    target_paths = [path for item in destinations for path in item.target_paths]
    if len(set(target_paths)) != len(target_paths):
        raise ValueError("acceptance destination paths must be unique")
    return destinations


def _parse_destination(source: Any) -> HandoffAcceptanceDestination:
    destination = _require_mapping(source, "acceptance destination")
    _require_keys(
        destination,
        {
            "measurement_record_id",
            "destination_record_id",
            "record_dir",
            "primary_data_path",
            "manifest_path",
            "storage_schema",
        },
        "acceptance destination",
    )
    measurement_record_id = validate_public_identifier(
        destination["measurement_record_id"],
        "acceptance destination measurement_record_id",
    )
    destination_record_id = validate_public_identifier(
        destination["destination_record_id"],
        "acceptance destination destination_record_id",
    )
    record_dir = validate_relative_path(destination["record_dir"], "acceptance record_dir")
    primary_data_path = validate_strict_child_path(
        destination["primary_data_path"],
        record_dir,
        "acceptance primary_data_path",
    )
    manifest_path = validate_strict_child_path(
        destination["manifest_path"],
        record_dir,
        "acceptance manifest_path",
    )
    if primary_data_path == manifest_path:
        raise ValueError("acceptance destination paths must be unique")
    storage_schema = validate_public_identifier(
        destination["storage_schema"],
        "acceptance destination storage_schema",
    )
    if storage_schema != "measurement_record_directory_candidate_v0":
        raise ValueError("acceptance destination storage_schema is unsupported")
    return HandoffAcceptanceDestination(
        measurement_record_id=measurement_record_id,
        destination_record_id=destination_record_id,
        record_dir=record_dir,
        primary_data_path=primary_data_path,
        manifest_path=manifest_path,
        storage_schema=storage_schema,
    )


def _validate_against_import_plan(
    *,
    request: HandoffAcceptancePreflightRequest,
    import_plan: HandoffImportPlanRun,
) -> None:
    if request.requested_package_id != import_plan.package.package_id:
        raise ValueError("requested package id must match import plan package")
    planned_ids = tuple(
        plan.measurement.measurement_record_id for plan in import_plan.measurement_plans
    )
    if not import_plan.import_plan_allowed:
        return
    if request.measurement_ids != planned_ids:
        raise ValueError("acceptance destinations must match import plan measurement ids")
