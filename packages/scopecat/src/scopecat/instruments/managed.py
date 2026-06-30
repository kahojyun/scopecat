"""Author-facing native instrument helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.experiments import ExperimentSpec
from scopecat.instruments.sdk import (
    CapabilityDescription,
    CapabilityField,
    CapabilityFieldKind,
    InstrumentDescription,
    InstrumentStateField,
    InstrumentStatePatch,
    InstrumentStateSnapshot,
    NativeAcquisitionContext,
    NativeInstrument,
    NativeInstrumentProviderContext,
    NativeInstrumentProviderDescription,
    NativeInstrumentProviderResult,
    NativeInstrumentResult,
)
from scopecat.instruments.state import (
    DesiredResourceState,
    ExecutionPoint,
    StatePatchField,
    StateValue,
)
from scopecat.models.artifact import ArtifactRef
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.results import MeasurementDatasetSchema, MeasurementSink
from scopecat.units import compatible_units


@dataclass(frozen=True)
class NativeDriverDiagnostic(Exception):
    """Stable diagnostic that driver code can raise or return."""

    severity: DiagnosticSeverity
    code: str
    message: str
    path: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            severity=self.severity,
            code=self.code,
            message=self.message,
            path=self.path,
        )


@dataclass(frozen=True)
class NativeCapabilityField:
    id: str
    kind: CapabilityFieldKind
    unit: str | None = None
    required: bool = True
    asset_kinds: tuple[str, ...] = ()
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_sdk_field(self) -> CapabilityField:
        metadata = dict(self.metadata)
        if self.asset_kinds:
            metadata["asset_kinds"] = list(self.asset_kinds)
        return CapabilityField(
            id=self.id,
            kind=self.kind,
            unit=self.unit,
            required=self.required,
            metadata=metadata,
        )


@dataclass(frozen=True)
class NativeCapability:
    id: str
    fields: tuple[NativeCapabilityField, ...] = ()
    acquisition: bool = False
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_sdk_capability(self) -> CapabilityDescription:
        return CapabilityDescription(
            id=self.id,
            fields=[field.to_sdk_field() for field in self.fields],
            acquisition=self.acquisition,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class NativeStateChange:
    instrument_id: str
    fields: tuple[StatePatchField, ...]
    desired_state: tuple[DesiredResourceState, ...] = ()

    def get(self, capability_id: str, field_path: str) -> StateValue | None:
        for field in self.fields:
            if field.capability_id == capability_id and field.field_path == field_path:
                return field.after
        return None

    def quantity(self, capability_id: str, field_path: str) -> Quantity | None:
        value = self.get(capability_id, field_path)
        return value.quantity if value is not None else None

    def number(self, capability_id: str, field_path: str) -> float | None:
        value = self.get(capability_id, field_path)
        return value.value if value is not None else None

    def asset_id(self, capability_id: str, field_path: str) -> str | None:
        value = self.get(capability_id, field_path)
        return value.asset_id if value is not None else None


@dataclass(frozen=True)
class NativeMeasurementContext:
    run_id: str
    point: ExecutionPoint
    point_index: int
    point_count: int
    coordinates: dict[str, Quantity]
    records_for_point: int
    record_index_offset: int
    acquisition_kind: str | None
    record: str | None
    expected_schema: MeasurementDatasetSchema | None
    desired_state: tuple[DesiredResourceState, ...]

    @classmethod
    def from_native_context(
        cls, context: NativeAcquisitionContext
    ) -> NativeMeasurementContext:
        acquisition = context.acquisition_plan
        expected_schema = (
            MeasurementDatasetSchema.model_validate(
                context.plan.expected_dataset_schema
            )
            if context.plan.expected_dataset_schema is not None
            else None
        )
        return cls(
            run_id=context.run_id,
            point=context.point,
            point_index=context.point.index,
            point_count=context.point_count,
            coordinates=dict(context.point.coordinates),
            records_for_point=context.records_for_point,
            record_index_offset=context.record_index_offset,
            acquisition_kind=acquisition.kind if acquisition is not None else None,
            record=acquisition.record if acquisition is not None else None,
            expected_schema=expected_schema,
            desired_state=tuple(context.desired_state),
        )


@dataclass
class NativeProviderBuildContext:
    config: ConfigProfileSnapshot
    experiment: ExperimentSpec
    assets: Mapping[str, ArtifactRef]
    diagnostics: list[Diagnostic] = dc_field(default_factory=list)

    def asset(self, asset_id: str) -> ArtifactRef | None:
        return self.assets.get(asset_id)

    def error(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        severity: DiagnosticSeverity = "error",
    ) -> Diagnostic:
        diagnostic = Diagnostic(
            severity=severity,
            code=code,
            message=message,
            path=path,
        )
        self.diagnostics.append(diagnostic)
        return diagnostic


DriverDiagnosticInput = Diagnostic | NativeDriverDiagnostic
ProviderFactory = Callable[[NativeProviderBuildContext], Iterable[NativeInstrument]]


class ManagedNativeInstrument:
    """Native instrument base class that hides the runner protocol details."""

    def __init__(
        self,
        *,
        instrument_id: str,
        implementation_id: str,
        implementation_version: str,
        capabilities: Sequence[NativeCapability],
        metadata: Mapping[str, Any] | None = None,
        initial_state: Mapping[tuple[str, str], StateValue] | None = None,
        asset_catalog: Mapping[str, ArtifactRef] | None = None,
    ) -> None:
        self.instrument_id = instrument_id
        self.implementation_id = implementation_id
        self.implementation_version = implementation_version
        self._capabilities = tuple(capabilities)
        self._metadata = dict(metadata or {})
        self._state = dict(initial_state or {})
        self._asset_catalog = dict(asset_catalog or {})
        self._field_specs = {
            (capability.id, field.id): field
            for capability in self._capabilities
            for field in capability.fields
        }
        self._capability_ids = {capability.id for capability in self._capabilities}

    def attach_assets(self, assets: Mapping[str, ArtifactRef]) -> None:
        self._asset_catalog = dict(assets)

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability.to_sdk_capability() for capability in self._capabilities
            ],
            metadata=self._metadata,
        )

    def validate(self, desired: list[DesiredResourceState]) -> list[Diagnostic]:
        diagnostics = self._validate_declared_fields(desired)
        if diagnostics:
            return diagnostics
        change = self._state_change_from_desired(desired)
        try:
            diagnostics.extend(_normalize_diagnostics(self.validate_state(change)))
        except NativeDriverDiagnostic as error:
            diagnostics.append(error.to_diagnostic())
        return diagnostics

    def validate_state(
        self, changes: NativeStateChange
    ) -> Iterable[DriverDiagnosticInput]:
        del changes
        return ()

    def readback(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=[
                InstrumentStateField(
                    capability_id=capability_id,
                    field_path=field_path,
                    value=value,
                )
                for (capability_id, field_path), value in sorted(self._state.items())
            ],
            metadata=self._metadata,
        )

    def diff(
        self,
        current: InstrumentStateSnapshot,
        desired: list[DesiredResourceState],
    ) -> InstrumentStatePatch:
        current_by_key = {
            (field.capability_id, field.field_path): field.value
            for field in current.fields
        }
        patch_fields: list[StatePatchField] = []
        for resource in desired:
            for field in resource.fields:
                key = (resource.capability_id, field.field_path)
                before = current_by_key.get(key)
                if before != field.value:
                    patch_fields.append(
                        StatePatchField(
                            resource_id=self.instrument_id,
                            capability_id=resource.capability_id,
                            field_path=field.field_path,
                            before=before,
                            after=field.value,
                        )
                    )
        return InstrumentStatePatch(
            instrument_id=self.instrument_id, fields=patch_fields
        )

    def apply(self, patch: InstrumentStatePatch) -> InstrumentStateSnapshot:
        change = NativeStateChange(
            instrument_id=self.instrument_id,
            fields=tuple(patch.fields),
        )
        self.apply_state(change)
        for field in patch.fields:
            self._state[(field.capability_id, field.field_path)] = field.after
        return self.readback()

    def apply_state(self, changes: NativeStateChange) -> None:
        del changes

    def acquire(
        self,
        context: NativeAcquisitionContext,
        sink: MeasurementSink,
    ) -> NativeInstrumentResult:
        try:
            self.measure(NativeMeasurementContext.from_native_context(context), sink)
        except NativeDriverDiagnostic as error:
            return NativeInstrumentResult(diagnostics=[error.to_diagnostic()])
        return NativeInstrumentResult()

    def measure(
        self,
        context: NativeMeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        del context, sink

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None

    def _state_change_from_desired(
        self, desired: list[DesiredResourceState]
    ) -> NativeStateChange:
        fields: list[StatePatchField] = []
        for resource in desired:
            for field in resource.fields:
                key = (resource.capability_id, field.field_path)
                fields.append(
                    StatePatchField(
                        resource_id=self.instrument_id,
                        capability_id=resource.capability_id,
                        field_path=field.field_path,
                        before=self._state.get(key),
                        after=field.value,
                    )
                )
        return NativeStateChange(
            instrument_id=self.instrument_id,
            fields=tuple(fields),
            desired_state=tuple(desired),
        )

    def _validate_declared_fields(
        self, desired: list[DesiredResourceState]
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for resource in desired:
            if resource.resource_id != self.instrument_id:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "managed_native_resource_mismatch",
                        f"{self.instrument_id} cannot control {resource.resource_id}",
                        "resource_id",
                    )
                )
            if resource.capability_id not in self._capability_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "managed_native_unsupported_capability",
                        f"{self.instrument_id} does not support "
                        f"{resource.capability_id}",
                        "capability_id",
                    )
                )
                continue
            for field in resource.fields:
                spec = self._field_specs.get((resource.capability_id, field.field_path))
                if spec is None:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "managed_native_unsupported_field",
                            f"{self.instrument_id} does not support {field.field_path}",
                            "field_path",
                        )
                    )
                    continue
                diagnostics.extend(_validate_value(field.field_path, field.value, spec))
                if spec.kind == "asset":
                    diagnostics.extend(
                        _validate_asset_field(
                            field_path=field.field_path,
                            value=field.value,
                            spec=spec,
                            assets=self._asset_catalog,
                        )
                    )
        return diagnostics

    def validate_asset_binding(
        self,
        *,
        capability_id: str,
        field_path: str,
        asset_id: str,
    ) -> list[Diagnostic]:
        spec = self._field_specs.get((capability_id, field_path))
        if spec is None or spec.kind != "asset":
            return []
        return _validate_asset_field(
            field_path=field_path,
            value=StateValue(kind="asset", asset_id=asset_id),
            spec=spec,
            assets=self._asset_catalog,
        )


class ManagedNativeProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        build: ProviderFactory,
        label: str | None = None,
        description: str | None = None,
        options: Sequence[ProviderOptionDescription] = (),
        provided_instrument_ids: Sequence[str] = (),
        capabilities: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._build = build
        self._label = label
        self._description = description
        self._options = tuple(options)
        self._provided_instrument_ids = tuple(provided_instrument_ids)
        self._capabilities = tuple(capabilities)
        self._metadata = dict(metadata or {})

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def describe(self) -> NativeInstrumentProviderDescription:
        return NativeInstrumentProviderDescription(
            provider_id=self.provider_id,
            label=self._label,
            description=self._description,
            options=self._options,
            provided_instrument_ids=self._provided_instrument_ids,
            capabilities=self._capabilities,
            metadata=self._metadata,
        )

    def provide(
        self, context: NativeInstrumentProviderContext
    ) -> NativeInstrumentProviderResult:
        assets = _experiment_assets(context.experiment)
        build_context = NativeProviderBuildContext(
            config=context.config,
            experiment=context.experiment,
            assets=assets,
        )
        try:
            instruments = tuple(self._build(build_context))
        except NativeDriverDiagnostic as error:
            build_context.diagnostics.append(error.to_diagnostic())
            instruments = ()
        for instrument in instruments:
            if isinstance(instrument, ManagedNativeInstrument):
                instrument.attach_assets(assets)
        return NativeInstrumentProviderResult(
            instruments=() if build_context.diagnostics else instruments,
            diagnostics=tuple(build_context.diagnostics),
            metadata={
                "provider_id": self.provider_id,
                "asset_ids": sorted(assets),
                **self._metadata,
            },
        )


def _experiment_assets(
    experiment: ExperimentSpec,
) -> dict[str, ArtifactRef]:
    return {asset.id: asset for asset in experiment.assets}


def capability(
    id: str,  # noqa: A002
    *,
    fields: Sequence[NativeCapabilityField] = (),
    acquisition: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> NativeCapability:
    return NativeCapability(
        id=id,
        fields=tuple(fields),
        acquisition=acquisition,
        metadata=dict(metadata or {}),
    )


def quantity_field(
    id: str,  # noqa: A002
    *,
    unit: str,
    required: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> NativeCapabilityField:
    return NativeCapabilityField(
        id=id,
        kind="quantity",
        unit=unit,
        required=required,
        metadata=dict(metadata or {}),
    )


def number_field(
    id: str,  # noqa: A002
    *,
    required: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> NativeCapabilityField:
    return NativeCapabilityField(
        id=id,
        kind="number",
        required=required,
        metadata=dict(metadata or {}),
    )


def asset_field(
    id: str,  # noqa: A002
    *,
    asset_kinds: Sequence[str] = (),
    required: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> NativeCapabilityField:
    return NativeCapabilityField(
        id=id,
        kind="asset",
        required=required,
        asset_kinds=tuple(asset_kinds),
        metadata=dict(metadata or {}),
    )


def _validate_value(
    field_path: str,
    value: StateValue,
    spec: NativeCapabilityField,
) -> list[Diagnostic]:
    if value.kind != spec.kind:
        return [
            _diagnostic(
                "error",
                "managed_native_field_kind_mismatch",
                f"{field_path} must be {spec.kind}, got {value.kind}",
                "value",
            )
        ]
    if spec.kind == "quantity":
        if value.quantity is None:
            return [
                _diagnostic(
                    "error",
                    "managed_native_field_not_quantity",
                    f"{field_path} must be a quantity",
                    "value",
                )
            ]
        if spec.unit is not None and not compatible_units(
            spec.unit, value.quantity.unit
        ):
            return [
                _diagnostic(
                    "error",
                    "managed_native_unit_mismatch",
                    f"{field_path} must use {spec.unit}-compatible units",
                    "value.unit",
                )
            ]
    return []


def _validate_asset_field(
    *,
    field_path: str,
    value: StateValue,
    spec: NativeCapabilityField,
    assets: Mapping[str, ArtifactRef],
) -> list[Diagnostic]:
    if not assets:
        return []
    asset = assets.get(value.asset_id or "")
    if asset is None:
        return [
            _diagnostic(
                "error",
                "managed_native_unknown_asset",
                f"{field_path} references unknown asset {value.asset_id}",
                "value.asset_id",
            )
        ]
    if spec.asset_kinds and asset.kind not in spec.asset_kinds:
        return [
            _diagnostic(
                "error",
                "managed_native_asset_kind_mismatch",
                f"{field_path} expects asset kind {', '.join(spec.asset_kinds)}, "
                f"got {asset.kind}",
                "value.asset_id",
            )
        ]
    return []


def _normalize_diagnostics(
    diagnostics: Iterable[DriverDiagnosticInput],
) -> list[Diagnostic]:
    normalized: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, NativeDriverDiagnostic):
            normalized.append(diagnostic.to_diagnostic())
        else:
            normalized.append(diagnostic)
    return normalized


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "ManagedNativeInstrument",
    "ManagedNativeProvider",
    "NativeDriverDiagnostic",
    "NativeMeasurementContext",
    "NativeProviderBuildContext",
    "NativeStateChange",
    "asset_field",
    "capability",
    "number_field",
    "quantity_field",
]
