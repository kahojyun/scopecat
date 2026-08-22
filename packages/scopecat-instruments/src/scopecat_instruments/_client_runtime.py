"""Shared live-client runtime used by generated instrument families."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.api.instruments import (
    InstrumentClientChannel,
    OperationArgumentValue,
)
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.kernel.value_types import ValueType
from scopecat.kernel.value_validation import coerce_literal
from scopecat.program.measurement_types import (
    MeasurementDType,
    MeasurementVariableRole,
)
from scopecat.records.instrument import (
    InstrumentStateCacheEntry,
    InstrumentStateCacheReadback,
    InstrumentStateObservation,
    InstrumentStateReadback,
    InstrumentStateSnapshot,
    InterfaceStateMemberTarget,
)
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    ApplyReceipt,
    InstrumentCollectFailure,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentDescription,
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
    PropertySpec,
)
from scopecat.sdk.instruments.contracts import resolve_state_member_spec
from scopecat.sdk.instruments.declarations import (
    member_projection_assignments,
)
from scopecat.sdk.problems import ProblemPhase, model_location, problem


@dataclass(frozen=True, slots=True)
class ClientMemberDeclaration:
    python_name: str
    ref: PropertyRef
    value_type: ValueType

    def decode(self, value: object, /) -> object:
        return coerce_literal(
            self.value_type,
            value,
            path=("state_member", self.python_name),
        )


@dataclass(frozen=True, slots=True)
class InstrumentMemberClient[ValueT]:
    """One independently observed and writable interface property."""

    _session: InstrumentClientChannel = field(repr=False)
    instrument_id: str
    declaration: ClientMemberDeclaration
    _portable_writable: bool
    _portable_readable: bool = True

    def implementation(self) -> PropertySpec:
        """Return this physical member's effective access and lifecycle policy."""

        target = self.declaration.ref
        physical_target = self._session.state_member_ref(target)
        if not isinstance(physical_target, PropertyRef):
            raise AssertionError("interface member resolved to a device property")
        resolved = resolve_state_member_spec(
            self._session.describe(self.instrument_id),
            InterfaceStateMemberTarget(
                interface_id=physical_target.interface_id,
                component_path=physical_target.component_path,
                property_id=physical_target.property_id,
            ),
        )
        if resolved is None:
            raise ValueError(
                f"instrument {self.instrument_id!r} does not implement "
                f"{self.declaration.ref!r}"
            )
        return resolved

    def is_writable(self) -> bool:
        """Return whether this concrete instrument endpoint accepts assignments."""

        return self._portable_writable and self.implementation().access != "read_only"

    def is_readable(self) -> bool:
        """Return whether this concrete instrument endpoint supports observation."""

        return self._portable_readable

    def observed(self) -> ValueT:
        entry = self.observed_entry()
        if entry.status != "observed" or entry.observation is None:
            detail = f": {entry.reason}" if entry.reason is not None else ""
            raise ValueError(
                f"instrument member {self.declaration.ref!r} cache is "
                f"{entry.status}{detail}"
            )
        return self._decode_observation(entry.observation)

    def observed_entry(self) -> InstrumentStateCacheEntry:
        """Return cached value evidence or its explicit unavailable status."""

        if not self.is_readable():
            raise TypeError(f"instrument member {self.declaration.ref!r} is write-only")
        cache = self._session.observed_state_members(
            self.instrument_id,
            self.declaration.ref,
        )
        return self._cache_entry(cache)

    def read(self) -> ValueT:
        return self._decode_observation(self.read_observation())

    def read_observation(self) -> InstrumentStateObservation:
        """Query and return the member value with its observation evidence."""

        if not self.is_readable():
            raise TypeError(f"instrument member {self.declaration.ref!r} is write-only")
        readback = self._session.read_state_members(
            self.instrument_id,
            self.declaration.ref,
        )
        return self._readback_observation(readback)

    def set(self, value: ValueT, /) -> ApplyReceipt:
        if not self.is_writable():
            raise TypeError(f"instrument member {self.declaration.ref!r} is read-only")
        return self._session.apply(
            {self.declaration.ref: StateValue.model_validate(value).root},
            instrument_id=self.instrument_id,
        )

    def _readback_observation(
        self,
        readback: InstrumentStateReadback,
    ) -> InstrumentStateObservation:
        observation = next(
            (item for item in readback.observations if self._matches(item.target)),
            None,
        )
        if observation is None:
            raise ValueError(
                f"observed state does not contain {self.declaration.ref!r}"
            )
        return observation

    def _cache_entry(
        self,
        cache: InstrumentStateCacheReadback,
    ) -> InstrumentStateCacheEntry:
        entry = next(
            (item for item in cache.entries if self._matches(item.target)),
            None,
        )
        if entry is None:
            raise ValueError(
                f"instrument cache does not contain {self.declaration.ref!r}"
            )
        return entry

    def _decode_observation(self, observation: InstrumentStateObservation) -> ValueT:
        return cast(
            "ValueT",
            self.declaration.decode(observation.value.root),
        )

    def _matches(self, target: object) -> bool:
        return isinstance(target, InterfaceStateMemberTarget) and PropertyRef(
            target.interface_id,
            target.component_path,
            target.property_id,
        ) == self._session.state_member_ref(self.declaration.ref)


@dataclass(frozen=True, slots=True)
class ClientAcquisitionAxis:
    id: str
    size: int | PropertyRef | None
    kind: str
    unit: str | None


@dataclass(frozen=True, slots=True)
class ClientAcquisitionResult:
    python_name: str
    ref: AcquisitionResultRef
    dtype: MeasurementDType
    unit: str | None
    role: MeasurementVariableRole
    axes: tuple[ClientAcquisitionAxis, ...]

    @property
    def result_id(self) -> str:
        return self.ref.result_id


@dataclass(frozen=True, slots=True)
class ClientAcquisition:
    ref: AcquisitionRef
    result_fields: tuple[ClientAcquisitionResult, ...]


def client_property_value_type(value_type_json: str, /) -> ValueType:
    return PropertySpec.model_validate_json(
        f'{{"id":"generated","value_type":{value_type_json}}}'
    ).value_type


@dataclass(frozen=True, slots=True)
class InstrumentClientBase:
    _session: InstrumentClientChannel = field(repr=False)
    instrument_id: str

    def describe(self) -> InstrumentDescription:
        return self._session.describe(self.instrument_id)

    def observed_state(self) -> InstrumentStateSnapshot:
        return self._session.observed_state(self.instrument_id)

    def refresh(self) -> InstrumentStateSnapshot:
        return self._session.read_state(self.instrument_id)

    def apply_defaults(self) -> InstrumentConfiguredDefaultsApplyReceipt:
        """Apply the configured sparse default state for this instrument."""

        return self._session.apply_configured_defaults(self.instrument_id)

    def _apply_declared(self, patch: object, /) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )

    def _member[ValueT](
        self,
        declaration: ClientMemberDeclaration,
        /,
        *,
        writable: bool,
        readable: bool = True,
    ) -> InstrumentMemberClient[ValueT]:
        return InstrumentMemberClient(
            self._session,
            self.instrument_id,
            declaration,
            writable,
            readable,
        )

    def _invoke(
        self,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, OperationArgumentValue],
        /,
    ) -> InvokeReceipt:
        return self._session.invoke(
            operation,
            arguments,
            instrument_id=self.instrument_id,
        )

    def _collect[OutputT](
        self,
        acquisition: ClientAcquisition,
        output_factory: Callable[..., OutputT],
    ) -> OutputT:
        requested_results = tuple(field.ref for field in acquisition.result_fields)
        receipt = self._session.collect(
            acquisition.ref,
            *requested_results,
            instrument_id=self.instrument_id,
        )
        if receipt.status != "collected":
            raise InstrumentCollectFailure(receipt)
        readback = receipt.readback
        if readback is None:
            raise AssertionError("validated collected receipt must contain readback")
        missing = tuple(
            field
            for field in acquisition.result_fields
            if field.result_id not in readback.values
        )
        if missing:
            raise ProviderContractError(
                tuple(
                    problem(
                        "instrument_collect_result_missing",
                        "collected readback is missing requested result "
                        f"{field.result_id!r}",
                        phase=ProblemPhase.EXECUTION,
                        location=model_location(
                            "collect_receipt",
                            "readback",
                            "values",
                            field.result_id,
                        ),
                        details={
                            "acquisition_id": acquisition.ref.acquisition_id,
                            "result_id": field.result_id,
                        },
                    )
                    for field in missing
                )
            )
        values = {
            field.python_name: readback.values[field.result_id]
            for field in acquisition.result_fields
        }
        return output_factory(receipt=receipt, **values)


class ProjectedMemberClientBase[StateT](InstrumentClientBase):
    def apply(self, patch: StateT) -> ApplyReceipt:
        return self._apply_declared(patch)

    def _apply_projected(
        self,
        patch: StateT | None,
        projection_factory: Callable[..., StateT],
        fields: Mapping[str, object],
        /,
    ) -> ApplyReceipt:
        if patch is not None and fields:
            raise TypeError("apply accepts either a patch or keyword fields")
        projected = projection_factory(**fields) if patch is None else patch
        return self._apply_declared(projected)

    def _apply_projected_fields(
        self,
        patch: StateT | None,
        properties: Mapping[str, PropertyRef],
        fields: Mapping[str, object],
        /,
    ) -> ApplyReceipt:
        if patch is not None and fields:
            raise TypeError("apply accepts either a patch or keyword fields")
        if patch is not None:
            return self._apply_declared(patch)
        return self._session.apply(
            _concrete_field_assignments(fields, properties),
            instrument_id=self.instrument_id,
        )


def _concrete_assignments(state: object) -> dict[PropertyRef, StateLiteral]:
    try:
        return {
            target: StateValue.model_validate(value).root
            for target, value in member_projection_assignments(state).items()
        }
    except ValueError as error:
        raise TypeError(
            "direct instrument patch must contain concrete values"
        ) from error


def _concrete_field_assignments(
    fields: Mapping[str, object],
    properties: Mapping[str, PropertyRef],
) -> dict[PropertyRef, StateLiteral]:
    unknown = tuple(name for name in fields if name not in properties)
    if unknown:
        raise TypeError(f"unknown instrument state field {unknown[0]!r}")
    try:
        return {
            properties[name]: StateValue.model_validate(value).root
            for name, value in fields.items()
        }
    except ValueError as error:
        raise TypeError(
            "direct instrument patch must contain concrete values"
        ) from error


__all__ = [
    "ClientAcquisition",
    "ClientAcquisitionAxis",
    "ClientAcquisitionResult",
    "ClientMemberDeclaration",
    "InstrumentClientBase",
    "InstrumentMemberClient",
    "ProjectedMemberClientBase",
    "client_property_value_type",
]
