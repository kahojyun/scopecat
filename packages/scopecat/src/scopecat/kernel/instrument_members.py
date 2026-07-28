"""Physical instrument member identities shared across Python APIs."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.interface_identity import InterfaceId, require_interface_id


def _validate_scope(
    interface_id: InterfaceId,
    component_path: tuple[str, ...],
) -> None:
    require_interface_id(interface_id)
    for component_id in component_path:
        _require_member_id(component_id, "component")


def _require_member_id(value: str, kind: str) -> None:
    if not value:
        raise ValueError(f"instrument {kind} id must be non-empty")


@dataclass(frozen=True, slots=True)
class InterfaceRef:
    interface_id: InterfaceId

    def __post_init__(self) -> None:
        require_interface_id(self.interface_id)

    def component(self, component_id: str) -> ComponentRef:
        return ComponentRef(self.interface_id, (component_id,))

    def property(self, property_id: str) -> PropertyRef:
        return PropertyRef(self.interface_id, (), property_id)

    def operation(self, operation_id: str) -> OperationRef:
        return OperationRef(self.interface_id, (), operation_id)

    def acquisition(self, acquisition_id: str) -> AcquisitionRef:
        return AcquisitionRef(self.interface_id, (), acquisition_id)


@dataclass(frozen=True, slots=True)
class ComponentRef:
    interface_id: InterfaceId
    component_path: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_scope(self.interface_id, self.component_path)
        if not self.component_path:
            raise ValueError("instrument component path must be non-empty")

    def component(self, component_id: str) -> ComponentRef:
        return ComponentRef(
            self.interface_id,
            (*self.component_path, component_id),
        )

    def property(self, property_id: str) -> PropertyRef:
        return PropertyRef(self.interface_id, self.component_path, property_id)

    def operation(self, operation_id: str) -> OperationRef:
        return OperationRef(self.interface_id, self.component_path, operation_id)

    def acquisition(self, acquisition_id: str) -> AcquisitionRef:
        return AcquisitionRef(self.interface_id, self.component_path, acquisition_id)


@dataclass(frozen=True, slots=True)
class PropertyRef:
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    property_id: str

    def __post_init__(self) -> None:
        _validate_scope(self.interface_id, self.component_path)
        _require_member_id(self.property_id, "property")


@dataclass(frozen=True, slots=True)
class OperationRef:
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    operation_id: str

    def __post_init__(self) -> None:
        _validate_scope(self.interface_id, self.component_path)
        _require_member_id(self.operation_id, "operation")


@dataclass(frozen=True, slots=True)
class AcquisitionRef:
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    acquisition_id: str

    def __post_init__(self) -> None:
        _validate_scope(self.interface_id, self.component_path)
        _require_member_id(self.acquisition_id, "acquisition")

    def result(self, result_id: str) -> AcquisitionResultRef:
        return AcquisitionResultRef(
            self.interface_id,
            self.component_path,
            self.acquisition_id,
            result_id,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionResultRef:
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    acquisition_id: str
    result_id: str

    def __post_init__(self) -> None:
        _validate_scope(self.interface_id, self.component_path)
        _require_member_id(self.acquisition_id, "acquisition")
        _require_member_id(self.result_id, "acquisition result")

    @property
    def acquisition(self) -> AcquisitionRef:
        return AcquisitionRef(
            self.interface_id,
            self.component_path,
            self.acquisition_id,
        )


__all__ = [
    "AcquisitionRef",
    "AcquisitionResultRef",
    "ComponentRef",
    "InterfaceRef",
    "OperationRef",
    "PropertyRef",
]
