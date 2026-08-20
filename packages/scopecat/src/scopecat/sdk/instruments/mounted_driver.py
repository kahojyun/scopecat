"""Route one physical instrument surface across mounted child drivers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.sdk.instruments.authoring import (
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverStateAssignment,
    DriverStateObservation,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    DriverUnknown,
)
from scopecat.sdk.instruments.contracts import (
    DeviceStateMemberSpec,
    DeviceStateSpec,
    InstrumentComponentSpec,
    InstrumentDescription,
    InterfaceMountSpec,
    InterfaceSpec,
)
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    DevicePropertyRef,
    OperationRef,
    PropertyRef,
    StateMemberRef,
)
from scopecat.sdk.instruments.provider import InstrumentDriver

type MountPath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Mount:
    path: MountPath
    driver: InstrumentDriver
    description: InstrumentDescription


@dataclass(slots=True)
class _ComponentNode:
    id: str | None = None
    label: str | None = None
    description: str | None = None
    children: dict[str, _ComponentNode] = field(default_factory=dict)

    def component(self) -> InstrumentComponentSpec:
        if self.id is None:
            raise AssertionError("the synthetic component root has no public spec")
        return InstrumentComponentSpec(
            id=self.id,
            label=self.label,
            description=self.description,
            components=[child.component() for child in self.children.values()],
        )


class MountedInstrumentRouter:
    """Compose relative child-driver surfaces at physical component paths.

    Child drivers remain responsible for their own member behavior. The router
    owns reference translation, description composition, multi-mount patch
    dispatch, and preservation of state/acquisition readback provenance. The
    containing physical driver continues to own transport identity and lifecycle.
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        implementation_id: str,
        implementation_version: str,
        mounts: Mapping[MountPath, InstrumentDriver],
        label: str | None = None,
        description: str | None = None,
        device_label: str | None = None,
        device_description: str | None = None,
    ) -> None:
        if not instrument_id:
            raise ValueError("mounted instrument id must be non-empty")
        if not implementation_id:
            raise ValueError("mounted implementation id must be non-empty")
        if not implementation_version:
            raise ValueError("mounted implementation version must be non-empty")
        normalized = tuple(
            sorted(
                (
                    _Mount(tuple(path), driver, driver.describe())
                    for path, driver in mounts.items()
                ),
                key=lambda item: item.path,
            )
        )
        if not normalized:
            raise ValueError("mounted instrument requires at least one child driver")
        for mount in normalized:
            if not mount.path or any(not component for component in mount.path):
                raise ValueError(
                    "mounted driver paths must contain non-empty components"
                )
        for index, left in enumerate(normalized):
            for right in normalized[index + 1 :]:
                if _path_prefix(left.path, right.path) or _path_prefix(
                    right.path, left.path
                ):
                    raise ValueError(
                        "mounted driver paths must not overlap: "
                        f"{_display_path(left.path)!r} and "
                        f"{_display_path(right.path)!r}"
                    )

        self.instrument_id = instrument_id
        self.implementation_id = implementation_id
        self.implementation_version = implementation_version
        self._mounts = normalized
        self._description = _compose_description(
            instrument_id=instrument_id,
            implementation_id=implementation_id,
            implementation_version=implementation_version,
            mounts=normalized,
            label=label,
            description=description,
            device_label=device_label,
            device_description=device_description,
        )

    def describe(self) -> InstrumentDescription:
        return self._description.model_copy(deep=True)

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        grouped: dict[MountPath, list[StateMemberRef]] = {}
        for target in sorted(request.targets, key=repr):
            mount = self._resolve(target.component_path, kind="state member")
            grouped.setdefault(mount.path, []).append(
                _state_member_at(target, target.component_path[len(mount.path) :])
            )

        mounted_readbacks: list[tuple[MountPath, DriverStateReadback]] = []
        for mount in self._mounts:
            targets = grouped.get(mount.path)
            if targets is None:
                continue
            readback = mount.driver.read_state(
                DriverStateReadRequest(frozenset(targets))
            )
            mounted_readbacks.append(
                (mount.path, _mount_state_readback(readback, mount.path))
            )
        return _combine_state_readbacks(mounted_readbacks)

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        grouped: dict[MountPath, list[DriverStateAssignment]] = {}
        try:
            for entry in request.entries:
                mount = self._resolve(entry.target.component_path, kind="state member")
                grouped.setdefault(mount.path, []).append(
                    DriverStateAssignment(
                        target=_state_member_at(
                            entry.target,
                            entry.target.component_path[len(mount.path) :],
                        ),
                        value=entry.value,
                        entity_ids=entry.entity_ids,
                        channel_bindings=entry.channel_bindings,
                    )
                )
        except ValueError as error:
            return _not_mounted(self.instrument_id, "state", str(error))

        completed: list[MountPath] = []
        readbacks: list[tuple[MountPath, DriverStateReadback]] = []
        outcome_metadata: dict[str, JsonValue] = {}
        for mount in self._mounts:
            entries = grouped.get(mount.path)
            if entries is None:
                continue
            outcome = mount.driver.apply_state(
                DriverStatePatch(scoped_values=tuple(entries))
            )
            if not isinstance(outcome, DriverSuccess):
                if completed:
                    return _partial_apply_unknown(
                        self.instrument_id,
                        completed=completed,
                        failed=mount.path,
                        outcome=outcome,
                    )
                return outcome
            completed.append(mount.path)
            if outcome.metadata:
                outcome_metadata[_display_path(mount.path)] = outcome.metadata
            if outcome.value is not None:
                readbacks.append(
                    (
                        mount.path,
                        _mount_state_readback(outcome.value, mount.path),
                    )
                )
        return DriverSuccess(
            None if not readbacks else _combine_state_readbacks(readbacks),
            metadata=_mounted_metadata(outcome_metadata),
        )

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        try:
            mount = self._resolve(request.target.component_path, kind="operation")
        except ValueError as error:
            return _not_mounted(self.instrument_id, "operation", str(error))
        outcome = mount.driver.invoke(
            DriverOperation(
                target=_operation_at(
                    request.target,
                    request.target.component_path[len(mount.path) :],
                ),
                arguments=request.arguments,
                entity_ids=request.entity_ids,
                channel_bindings=request.channel_bindings,
            )
        )
        if not isinstance(outcome, DriverSuccess) or outcome.value is None:
            return outcome
        return DriverSuccess(
            _mount_state_readback(outcome.value, mount.path),
            metadata=outcome.metadata,
        )

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        try:
            mount = self._resolve(request.target.component_path, kind="acquisition")
            rooted_results = frozenset(
                self._relative_result(result, mount) for result in request.results
            )
            rooted_dimensions = {
                self._relative_result(result, mount): dimensions
                for result, dimensions in request.dimensions.items()
            }
        except ValueError as error:
            return _not_mounted(self.instrument_id, "acquisition", str(error))

        outcome = mount.driver.collect(
            DriverAcquisition(
                target=_acquisition_at(
                    request.target,
                    request.target.component_path[len(mount.path) :],
                ),
                results=rooted_results,
                dimensions=rooted_dimensions,
                entity_ids=request.entity_ids,
                channel_bindings=request.channel_bindings,
            )
        )
        if not isinstance(outcome, DriverSuccess):
            return outcome
        return DriverSuccess(
            DriverReadback(
                values={
                    _result_at(result, (*mount.path, *result.component_path)): value
                    for result, value in outcome.value.values.items()
                },
                metadata=outcome.value.metadata,
            ),
            metadata=outcome.metadata,
        )

    def _resolve(self, component_path: Sequence[str], *, kind: str) -> _Mount:
        selected = tuple(component_path)
        for mount in self._mounts:
            if _path_prefix(mount.path, selected):
                return mount
        raise ValueError(
            f"{self.instrument_id} has no mounted {kind} at {_display_path(selected)!r}"
        )

    def _relative_result(
        self,
        result: AcquisitionResultRef,
        expected_mount: _Mount,
    ) -> AcquisitionResultRef:
        actual_mount = self._resolve(result.component_path, kind="acquisition result")
        if actual_mount.path != expected_mount.path:
            raise ValueError(
                f"{self.instrument_id} acquisition results cross mounted drivers"
            )
        return _result_at(
            result,
            result.component_path[len(expected_mount.path) :],
        )


def _compose_description(
    *,
    instrument_id: str,
    implementation_id: str,
    implementation_version: str,
    mounts: Sequence[_Mount],
    label: str | None,
    description: str | None,
    device_label: str | None,
    device_description: str | None,
) -> InstrumentDescription:
    root = _ComponentNode()
    interfaces: dict[str, InterfaceSpec] = {}
    interface_mounts: list[InterfaceMountSpec] = []
    device_specs: list[tuple[MountPath, DeviceStateSpec]] = []

    for mount in mounts:
        target_node = _ensure_component_path(root, mount.path)
        for component in mount.description.components:
            _merge_component(target_node, component)
        child_mounts: dict[str, list[tuple[str, ...]]] = {}
        for child_mount in mount.description.interface_mounts:
            child_mounts.setdefault(child_mount.interface_id, []).append(
                tuple(child_mount.component_path)
            )
        for interface in mount.description.interfaces:
            previous = interfaces.setdefault(
                interface.id, interface.model_copy(deep=True)
            )
            if previous != interface:
                raise ValueError(
                    f"mounted drivers declare conflicting interface {interface.id!r}"
                )
            relative_mounts = child_mounts.get(interface.id, [()])
            interface_mounts.extend(
                InterfaceMountSpec(
                    interface_id=interface.id,
                    component_path=[*mount.path, *relative_path],
                )
                for relative_path in relative_mounts
            )
        if mount.description.device_state is not None:
            device_specs.append((mount.path, mount.description.device_state))

    device_state: DeviceStateSpec | None = None
    if device_specs:
        schema_ids = {spec.id for _, spec in device_specs}
        if len(schema_ids) != 1:
            raise ValueError(
                "mounted child drivers expose multiple device schemas; "
                "one physical instrument description can expose only one"
            )
        first = device_specs[0][1]
        device_state = DeviceStateSpec(
            id=first.id,
            label=first.label if device_label is None else device_label,
            description=(
                first.description if device_description is None else device_description
            ),
            members=[
                DeviceStateMemberSpec(
                    component_path=[*path, *member.component_path],
                    property=member.property.model_copy(deep=True),
                )
                for path, spec in device_specs
                for member in spec.members
            ],
        )

    return InstrumentDescription(
        instrument_id=instrument_id,
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        label=label,
        description=description,
        components=[child.component() for child in root.children.values()],
        device_state=device_state,
        interfaces=list(interfaces.values()),
        interface_mounts=interface_mounts,
    )


def _ensure_component_path(root: _ComponentNode, path: MountPath) -> _ComponentNode:
    node = root
    for component_id in path:
        node = node.children.setdefault(component_id, _ComponentNode(id=component_id))
    return node


def _merge_component(
    parent: _ComponentNode, component: InstrumentComponentSpec
) -> None:
    node = parent.children.setdefault(component.id, _ComponentNode(id=component.id))
    if node.label is not None and component.label not in (None, node.label):
        raise ValueError(f"mounted component {component.id!r} has conflicting labels")
    if node.description is not None and component.description not in (
        None,
        node.description,
    ):
        raise ValueError(
            f"mounted component {component.id!r} has conflicting descriptions"
        )
    if component.label is not None:
        node.label = component.label
    if component.description is not None:
        node.description = component.description
    for child in component.components:
        _merge_component(node, child)


def _combine_state_readbacks(
    readbacks: Sequence[tuple[MountPath, DriverStateReadback]],
) -> DriverStateReadback:
    mount_metadata = {
        _display_path(path): readback.metadata
        for path, readback in readbacks
        if readback.metadata
    }
    return DriverStateReadback(
        observations=tuple(
            observation
            for _, readback in readbacks
            for observation in readback.observations
        ),
        metadata=_mounted_metadata(mount_metadata),
    )


def _mounted_metadata(
    metadata: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    return {} if not metadata else {"mounts": dict(metadata)}


def _mount_state_readback(
    readback: DriverStateReadback,
    mount_path: MountPath,
) -> DriverStateReadback:
    return DriverStateReadback(
        observations=tuple(
            DriverStateObservation(
                target=_state_member_at(
                    observation.target,
                    (*mount_path, *observation.target.component_path),
                ),
                value=observation.value,
                source=observation.source,
                coherence_id=observation.coherence_id,
                entity_ids=observation.entity_ids,
                channel_bindings=observation.channel_bindings,
            )
            for observation in readback.observations
        ),
        metadata=readback.metadata,
    )


def _state_member_at(
    target: StateMemberRef,
    component_path: Sequence[str],
) -> StateMemberRef:
    path = tuple(component_path)
    if isinstance(target, PropertyRef):
        return PropertyRef(target.interface_id, path, target.property_id)
    return DevicePropertyRef(target.schema_id, path, target.property_id)


def _operation_at(target: OperationRef, component_path: Sequence[str]) -> OperationRef:
    return OperationRef(target.interface_id, tuple(component_path), target.operation_id)


def _acquisition_at(
    target: AcquisitionRef,
    component_path: Sequence[str],
) -> AcquisitionRef:
    return AcquisitionRef(
        target.interface_id,
        tuple(component_path),
        target.acquisition_id,
    )


def _result_at(
    target: AcquisitionResultRef,
    component_path: Sequence[str],
) -> AcquisitionResultRef:
    return AcquisitionResultRef(
        target.interface_id,
        tuple(component_path),
        target.acquisition_id,
        target.result_id,
    )


def _not_mounted(instrument_id: str, kind: str, message: str) -> DriverRejected:
    return DriverRejected(
        problems=(
            problem(
                f"instrument_{kind}_not_mounted",
                message,
                phase=ProblemPhase.EXECUTION,
                location=model_location(f"driver_{kind}"),
                details={"instrument_id": instrument_id},
            ),
        )
    )


def _partial_apply_unknown(
    instrument_id: str,
    *,
    completed: Sequence[MountPath],
    failed: MountPath,
    outcome: DriverRejected | DriverUnknown,
) -> DriverUnknown:
    return DriverUnknown(
        problems=(
            problem(
                "instrument_partial_apply_outcome_unknown",
                f"{instrument_id} failed after applying earlier mounted state",
                phase=ProblemPhase.EXECUTION,
                location=model_location("driver_state_patch"),
                details={
                    "completed_mounts": [_display_path(path) for path in completed],
                    "failed_mount": _display_path(failed),
                    "failure_codes": [item.code for item in outcome.problems],
                },
            ),
        )
    )


def _path_prefix(prefix: Sequence[str], path: Sequence[str]) -> bool:
    return tuple(path[: len(prefix)]) == tuple(prefix)


def _display_path(path: Sequence[str]) -> str:
    return "/".join(path) or "<root>"


__all__ = ["MountPath", "MountedInstrumentRouter"]
