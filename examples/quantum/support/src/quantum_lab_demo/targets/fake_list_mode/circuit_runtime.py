"""Correlate fake target evidence to Scopecat logical quantum outputs.

The ordinary fake-list runtime remains usable as a target-specific component.
This adapter layer additionally proves that a compiled logical circuit or
mixed gate/pulse batch, its raw run, and every returned frame belong to the
same transient mapping chain.
Frames remain raw target evidence after correlation. Explicit per-result
laboratory bindings may then compose integrated-IQ shot arrays and raw
shot-by-sample traces in one exact pre-effect selection; target repetitions or
returned frame shape never select those policies implicitly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.measurements.results import ComplexQuantity, MeasurementArray
from scopecat.sdk.domain import (
    DomainMappedResult,
    DomainPointRef,
    DomainProductContractView,
    DomainProductUseRef,
    DomainResultValue,
)
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    PulseEventId,
    PulseProgramId,
    TargetCompileEntryId,
)
from scopecat_quantum.circuit_results import (
    CircuitTargetResultMapping,
    CompiledCircuitTarget,
)
from scopecat_quantum.circuit_targets import CircuitTargetAcquisitionOrigin
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
    QuantumTargetResultMapping,
)
from scopecat_quantum.program_targets import QuantumTargetAcquisitionOrigin
from scopecat_quantum.targets import TargetAcquisitionAddress

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeListArtifact,
    FakeListTarget,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeDigitizerFrame,
    FakeListRun,
    FakeListRuntime,
)

_FAKE_RESPONSE_UNIT = "ratio"

type _FakeListCompiledTarget = (
    CompiledCircuitTarget[FakeListArtifact] | CompiledQuantumTarget[FakeListArtifact]
)
type _FakeListResultMapping = CircuitTargetResultMapping | QuantumTargetResultMapping
type _FakeListAcquisitionOrigin = (
    CircuitTargetAcquisitionOrigin | QuantumTargetAcquisitionOrigin
)


@dataclass(frozen=True, slots=True, init=False)
class CorrelatedFakeListFrame:
    """One raw fake frame related to exact quantum and SDK identities."""

    frame: FakeDigitizerFrame
    mapped_result: DomainMappedResult[
        TargetCompileEntryId, TargetAcquisitionAddress
    ] = field(repr=False)
    acquisition_origin: _FakeListAcquisitionOrigin = field(repr=False)

    def __init__(
        self,
        frame: FakeDigitizerFrame,
        mapped_result: DomainMappedResult[
            TargetCompileEntryId, TargetAcquisitionAddress
        ],
        acquisition_origin: _FakeListAcquisitionOrigin,
    ) -> None:
        if mapped_result.result_address != frame.address:
            msg = "fake frame address does not identify its logical result"
            raise ValueError(msg)
        if acquisition_origin.address != frame.address:
            msg = "fake frame address does not identify its quantum acquisition"
            raise ValueError(msg)
        if mapped_result.entry_address != frame.entry_id:
            msg = "fake frame entry does not own its logical result"
            raise ValueError(msg)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "mapped_result", mapped_result)
        object.__setattr__(self, "acquisition_origin", acquisition_origin)

    @property
    def address(self) -> TargetAcquisitionAddress:
        return self.frame.address

    @property
    def shot_index(self) -> int:
        return self.frame.shot_index

    @property
    def point(self) -> DomainPointRef:
        return self.mapped_result.point

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self.mapped_result.product_uses

    @property
    def product(self) -> DomainProductContractView:
        return _mapped_result_product(self.mapped_result)


@dataclass(frozen=True, slots=True, init=False)
class CorrelatedFakeListRun:
    """Checked, canonically ordered fake target evidence."""

    compiled_target: _FakeListCompiledTarget
    target_run: FakeListRun
    frames: tuple[CorrelatedFakeListFrame, ...]
    _by_output_shot: Mapping[
        tuple[int, int, int],
        CorrelatedFakeListFrame,
    ] = field(repr=False, compare=False, hash=False)
    _by_address_shot: Mapping[
        tuple[TargetAcquisitionAddress, int],
        CorrelatedFakeListFrame,
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        compiled_target: _FakeListCompiledTarget,
        target_run: FakeListRun,
        frames: tuple[CorrelatedFakeListFrame, ...],
    ) -> None:
        mapping = compiled_target.mapping.domain_mapping
        compiled = compiled_target.compiled
        artifact = compiled.artifact
        if (
            target_run.artifact != artifact
            or target_run.artifact_id != compiled.artifact_id
            or target_run.artifact.artifact_fingerprint != compiled.artifact_fingerprint
        ):
            msg = "fake-list run does not belong to its compiled quantum target"
            raise ValueError(msg)

        selected_frames = tuple(frames)
        expected_order = tuple(
            (
                result.point,
                result.product_uses,
                result.result_address,
                shot_index,
            )
            for result in mapping.results
            for shot_index in range(compiled.repetitions)
        )
        actual_order = tuple(
            (
                item.point,
                item.product_uses,
                item.address,
                item.shot_index,
            )
            for item in selected_frames
        )
        if actual_order != expected_order:
            msg = (
                "correlated fake frames must exactly follow canonical "
                "physical-result/shot order"
            )
            raise ValueError(msg)

        by_output_shot = {
            (id(item.point), id(product_use), item.shot_index): item
            for item in selected_frames
            for product_use in item.product_uses
        }
        expected_output_shots = {
            (id(result.point), id(product_use), shot_index)
            for result in mapping.results
            for product_use in result.product_uses
            for shot_index in range(compiled.repetitions)
        }
        if set(by_output_shot) != expected_output_shots:
            msg = "correlated fake frames must cover every logical output shot"
            raise ValueError(msg)
        by_address_shot = {
            (item.address, item.shot_index): item for item in selected_frames
        }
        if len(by_address_shot) != len(selected_frames):
            msg = "correlated fake frames require unique physical result shots"
            raise ValueError(msg)
        raw_by_address_shot = {
            (frame.address, frame.shot_index): frame for frame in target_run.frames
        }
        if len(raw_by_address_shot) != len(target_run.frames):
            msg = "fake-list run contains duplicate acquisition-address shots"
            raise ValueError(msg)
        if set(by_address_shot) != set(raw_by_address_shot):
            msg = "correlated fake frames must exactly cover the target run"
            raise ValueError(msg)
        for item in selected_frames:
            if raw_by_address_shot[(item.address, item.shot_index)] is not item.frame:
                msg = "correlated fake frames must retain exact target frames"
                raise ValueError(msg)
            if mapping.result_for_address(item.address) is not item.mapped_result:
                msg = "correlated fake frame does not retain its mapping result"
                raise ValueError(msg)
            if (
                compiled_target.mapping.batch.acquisition_origin_for(item.address)
                is not item.acquisition_origin
            ):
                msg = "correlated fake frame does not retain its acquisition origin"
                raise ValueError(msg)

        object.__setattr__(self, "compiled_target", compiled_target)
        object.__setattr__(self, "target_run", target_run)
        object.__setattr__(self, "frames", selected_frames)
        object.__setattr__(
            self,
            "_by_output_shot",
            MappingProxyType(by_output_shot),
        )
        object.__setattr__(
            self,
            "_by_address_shot",
            MappingProxyType(by_address_shot),
        )

    @property
    def mapping(self) -> _FakeListResultMapping:
        return self.compiled_target.mapping

    @property
    def repetitions(self) -> int:
        return self.compiled_target.compiled.repetitions

    @property
    def raw_frames(self) -> tuple[FakeDigitizerFrame, ...]:
        """Return target-order frames before canonical logical projection."""

        return self.target_run.frames

    def frame_for_output(
        self,
        point: DomainPointRef,
        product_use: DomainProductUseRef,
        shot_index: int,
    ) -> CorrelatedFakeListFrame:
        _require_shot_index(shot_index)
        try:
            return self._by_output_shot[(id(point), id(product_use), shot_index)]
        except KeyError as error:
            msg = (
                "logical output shot is not in this fake-list run: "
                f"point={point.id!r}, use={product_use.id!r}, shot={shot_index}"
            )
            raise KeyError(msg) from error

    def frame_for_address(
        self,
        address: TargetAcquisitionAddress,
        shot_index: int,
    ) -> CorrelatedFakeListFrame:
        _require_shot_index(shot_index)
        self.mapping.domain_mapping.result_for_address(address)
        try:
            return self._by_address_shot[(address, shot_index)]
        except KeyError as error:
            msg = (
                "physical result shot is not in this fake-list run: "
                f"address={address!r}, shot={shot_index}"
            )
            raise KeyError(msg) from error

    def frames_for_address(
        self,
        address: TargetAcquisitionAddress,
    ) -> tuple[CorrelatedFakeListFrame, ...]:
        """Return physical frames once, independent of logical fan-out."""

        self.mapping.domain_mapping.result_for_address(address)
        return tuple(
            self.frame_for_address(address, shot_index)
            for shot_index in range(self.repetitions)
        )

    def frames_for_output(
        self,
        point: DomainPointRef,
        product_use: DomainProductUseRef,
    ) -> tuple[CorrelatedFakeListFrame, ...]:
        self.mapping.domain_mapping.result_for(point, product_use)
        return tuple(
            self.frame_for_output(point, product_use, shot_index)
            for shot_index in range(self.repetitions)
        )


class FakeMeasurementRealizationKind(StrEnum):
    """Explicit target-owned value policy for one acquisition result."""

    INTEGRATED_IQ_SHOTS = "integrated_iq_shots"
    RAW_TRACE_SHOTS = "raw_trace_shots"


@dataclass(frozen=True, slots=True)
class FakeMeasurementRealizationBinding:
    """Composable edge assigning one result address to one value policy."""

    result_address: TargetAcquisitionAddress
    kind: FakeMeasurementRealizationKind


@dataclass(frozen=True, slots=True, init=False)
class SelectedFakeMeasurementOutput:
    """One result-specific policy bound to public mapping inventory."""

    result: DomainMappedResult[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ] = field(repr=False)
    acquisition_origin: _FakeListAcquisitionOrigin = field(repr=False)
    acquisition_window: FakeAcquisitionWindow = field(repr=False)
    kind: FakeMeasurementRealizationKind

    def __init__(
        self,
        result: DomainMappedResult[
            TargetCompileEntryId,
            TargetAcquisitionAddress,
        ],
        acquisition_origin: _FakeListAcquisitionOrigin,
        acquisition_window: FakeAcquisitionWindow,
        kind: FakeMeasurementRealizationKind,
    ) -> None:
        if acquisition_origin.address != result.result_address:
            msg = "selected fake output origin must identify its logical result"
            raise ValueError(msg)
        if acquisition_window.slot_id != result.result_address.slot_id:
            msg = "selected fake output window must identify its logical result"
            raise ValueError(msg)
        expected_acquisition_kind = _acquisition_kind_for_realization(kind)
        if acquisition_window.kind is not expected_acquisition_kind:
            msg = "selected fake output window does not implement its value policy"
            raise ValueError(msg)
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "acquisition_origin", acquisition_origin)
        object.__setattr__(self, "acquisition_window", acquisition_window)
        object.__setattr__(self, "kind", kind)

    @property
    def result_address(self) -> TargetAcquisitionAddress:
        return self.result.result_address

    @property
    def point(self) -> DomainPointRef:
        return self.result.point

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self.result.product_uses


@dataclass(frozen=True, slots=True, init=False)
class SelectedFakeMeasurementRealization:
    """Exact pre-effect closure of heterogeneous fake measurement policies."""

    compiled_target: _FakeListCompiledTarget = field(repr=False)
    target: FakeListTarget = field(repr=False)
    outputs: tuple[SelectedFakeMeasurementOutput, ...]
    _by_address: Mapping[
        TargetAcquisitionAddress,
        SelectedFakeMeasurementOutput,
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        compiled_target: _FakeListCompiledTarget,
        target: FakeListTarget,
        outputs: tuple[SelectedFakeMeasurementOutput, ...],
    ) -> None:
        artifact = compiled_target.compiled.artifact
        if (
            target.id != compiled_target.compiled.target_id
            or target.capability_fingerprint
            != compiled_target.compiled.capability_fingerprint
            or target.sample_rate_hz != artifact.sample_rate_hz
        ):
            msg = "fake measurement selection target does not match its artifact"
            raise ValueError(msg)
        mapping = compiled_target.mapping.domain_mapping
        selected_outputs = tuple(outputs)
        mapping_results = mapping.results
        if len(selected_outputs) != len(mapping_results) or any(
            output.result is not result
            for output, result in zip(selected_outputs, mapping_results, strict=True)
        ):
            msg = (
                "selected fake measurement outputs must exactly follow canonical "
                "mapping result order"
            )
            raise ValueError(msg)
        by_address = {output.result_address: output for output in selected_outputs}
        if len(by_address) != len(selected_outputs):
            msg = "selected fake measurement outputs require unique result addresses"
            raise ValueError(msg)
        object.__setattr__(self, "compiled_target", compiled_target)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "outputs", selected_outputs)
        object.__setattr__(self, "_by_address", MappingProxyType(by_address))

    @property
    def mapping(self) -> _FakeListResultMapping:
        return self.compiled_target.mapping

    @property
    def repetitions(self) -> int:
        return self.compiled_target.compiled.repetitions

    def output_for_address(
        self,
        result_address: TargetAcquisitionAddress,
    ) -> SelectedFakeMeasurementOutput:
        try:
            return self._by_address[result_address]
        except KeyError as error:
            msg = f"result address {result_address!r} has no selected fake policy"
            raise KeyError(msg) from error


@dataclass(frozen=True, slots=True, init=False)
class RealizedFakeMeasurementRun:
    """One mixed-policy fake run decoded to public SDK result values."""

    selection: SelectedFakeMeasurementRealization = field(repr=False)
    correlated_run: CorrelatedFakeListRun = field(repr=False)
    result_values: tuple[DomainResultValue[TargetAcquisitionAddress], ...]
    _by_address: Mapping[
        TargetAcquisitionAddress,
        DomainResultValue[TargetAcquisitionAddress],
    ] = field(repr=False, compare=False)

    def __init__(
        self,
        selection: SelectedFakeMeasurementRealization,
        correlated_run: CorrelatedFakeListRun,
        result_values: tuple[DomainResultValue[TargetAcquisitionAddress], ...],
    ) -> None:
        selected_values = tuple(result_values)
        if selection.compiled_target is not correlated_run.compiled_target:
            msg = (
                "fake measurement realization must use the exact pre-effect "
                "compiled-target selection"
            )
            raise ValueError(msg)
        expected_addresses = tuple(
            output.result_address for output in selection.outputs
        )
        if (
            tuple(value.result_address for value in selected_values)
            != expected_addresses
        ):
            msg = "fake measurement values must follow selected result address order"
            raise ValueError(msg)
        by_address = {value.result_address: value for value in selected_values}
        if len(by_address) != len(selected_values):
            msg = "fake measurement values require unique result addresses"
            raise ValueError(msg)
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "correlated_run", correlated_run)
        object.__setattr__(self, "result_values", selected_values)
        object.__setattr__(self, "_by_address", MappingProxyType(by_address))

    @property
    def mapping(self) -> _FakeListResultMapping:
        return self.selection.mapping

    def value_for_output(
        self,
        point: DomainPointRef,
        product_use: DomainProductUseRef,
    ) -> DomainResultValue[TargetAcquisitionAddress]:
        mapped = self.mapping.domain_mapping.result_for(point, product_use)
        return self._by_address[mapped.result_address]

    def frames_for_output(
        self,
        point: DomainPointRef,
        product_use: DomainProductUseRef,
    ) -> tuple[CorrelatedFakeListFrame, ...]:
        """Recover the exact raw frames from which one value was realized."""

        self.value_for_output(point, product_use)
        return self.correlated_run.frames_for_output(point, product_use)


def integrated_iq_shots(
    result_address: TargetAcquisitionAddress,
) -> FakeMeasurementRealizationBinding:
    """Declare an integrated-IQ shot-array policy for one mapped result."""

    return FakeMeasurementRealizationBinding(
        result_address,
        FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS,
    )


def raw_trace_shots(
    result_address: TargetAcquisitionAddress,
) -> FakeMeasurementRealizationBinding:
    """Declare a shot-by-sample raw-trace policy for one mapped result."""

    return FakeMeasurementRealizationBinding(
        result_address,
        FakeMeasurementRealizationKind.RAW_TRACE_SHOTS,
    )


def select_fake_measurement_realization(
    compiled_target: _FakeListCompiledTarget,
    target: FakeListTarget,
    bindings: Sequence[FakeMeasurementRealizationBinding],
) -> SelectedFakeMeasurementRealization:
    """Seal explicit per-result value policies before target effects."""

    selected_bindings = tuple(bindings)
    selected_outputs = _select_fake_measurement_outputs(
        compiled_target,
        target,
        selected_bindings,
    )
    return SelectedFakeMeasurementRealization(
        compiled_target,
        target,
        selected_outputs,
    )


def correlate_fake_list_run(
    compiled_target: _FakeListCompiledTarget,
    target_run: FakeListRun,
) -> CorrelatedFakeListRun:
    """Revalidate and correlate one raw fake run without interpreting values."""

    target_mapping = compiled_target.mapping
    mapping = target_mapping.domain_mapping
    compiled = compiled_target.compiled
    artifact = compiled.artifact
    if target_run.artifact != artifact:
        msg = "fake-list run does not retain the compiled target artifact"
        raise ValueError(msg)

    raw_by_address_shot = {
        (frame.address, frame.shot_index): frame for frame in target_run.frames
    }
    if len(raw_by_address_shot) != len(target_run.frames):
        msg = "fake-list run contains duplicate acquisition-address shots"
        raise ValueError(msg)
    expected_keys = {
        (result.result_address, shot_index)
        for result in mapping.results
        for shot_index in range(compiled.repetitions)
    }
    if set(raw_by_address_shot) != expected_keys:
        msg = (
            "fake-list frames must exactly cover every mapped acquisition for "
            "every shot"
        )
        raise ValueError(msg)

    correlated_frames = tuple(
        CorrelatedFakeListFrame(
            frame=raw_by_address_shot[(result.result_address, shot_index)],
            mapped_result=result,
            acquisition_origin=target_mapping.batch.acquisition_origin_for(
                result.result_address
            ),
        )
        for result in mapping.results
        for shot_index in range(compiled.repetitions)
    )
    return CorrelatedFakeListRun(
        compiled_target,
        target_run,
        correlated_frames,
    )


def execute_correlated_fake_list(
    runtime: FakeListRuntime,
    compiled_target: _FakeListCompiledTarget,
) -> CorrelatedFakeListRun:
    """Execute the synchronous fake target and correlate its returned evidence."""

    target_run = runtime.execute(compiled_target.compiled)
    return correlate_fake_list_run(compiled_target, target_run)


def realize_fake_measurements(
    selection: SelectedFakeMeasurementRealization,
    correlated_run: CorrelatedFakeListRun,
) -> RealizedFakeMeasurementRun:
    """Accept one correlated run under its exact per-result policies."""

    if selection.compiled_target is not correlated_run.compiled_target:
        msg = "fake measurement realization requires the selected compiled target"
        raise ValueError(msg)

    candidates: list[DomainResultValue[TargetAcquisitionAddress]] = []
    problems: list[Problem] = []
    for result_index, selected_output in enumerate(selection.outputs):
        frames = correlated_run.frames_for_address(selected_output.result_address)
        if selected_output.kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS:
            value = _realize_integrated_iq_value(
                selected_output,
                frames,
                result_index=result_index,
                problems=problems,
            )
        else:
            value = _realize_raw_trace_value(
                selected_output,
                frames,
                result_index=result_index,
                problems=problems,
            )
        if value is not None:
            candidates.append(DomainResultValue(selected_output.result_address, value))
    if problems:
        raise ProviderContractError(problems)

    return RealizedFakeMeasurementRun(
        selection,
        correlated_run,
        tuple(candidates),
    )


def execute_realized_fake_measurements(
    runtime: FakeListRuntime,
    selection: SelectedFakeMeasurementRealization,
) -> RealizedFakeMeasurementRun:
    """Execute only after every mapped result has one selected policy."""

    correlated_run = execute_correlated_fake_list(runtime, selection.compiled_target)
    return realize_fake_measurements(selection, correlated_run)


def _realize_integrated_iq_value(
    selected_output: SelectedFakeMeasurementOutput,
    frames: tuple[CorrelatedFakeListFrame, ...],
    *,
    result_index: int,
    problems: list[Problem],
) -> MeasurementArray | None:
    initial_problem_count = len(problems)
    result = selected_output.result
    details = _realization_identity_details(result)
    path = ("results", result_index)
    complex_values: list[complex] = []
    for shot_index, frame in enumerate(frames):
        frame_path = (*path, "frames", shot_index)
        if frame.shot_index != shot_index:
            problems.append(
                _realization_problem(
                    "fake_integrated_iq_shot_identity_mismatch",
                    "fake integrated-IQ frames must retain contiguous shot "
                    f"identity; expected {shot_index}, got {frame.shot_index}",
                    path=(*frame_path, "shot_index"),
                    details={
                        **details,
                        "expected": shot_index,
                        "actual": frame.shot_index,
                    },
                )
            )
        if frame.frame.kind is not AcquisitionKind.INTEGRATED_IQ:
            problems.append(
                _realization_problem(
                    "fake_integrated_iq_frame_kind_mismatch",
                    "fake integrated-IQ realization cannot accept acquisition "
                    f"kind {frame.frame.kind.value!r}",
                    path=(*frame_path, "kind"),
                    details={
                        **details,
                        "expected": AcquisitionKind.INTEGRATED_IQ.value,
                        "actual": frame.frame.kind.value,
                    },
                )
            )
            continue
        complex_values.append(cast("complex", frame.frame.value))
    if len(problems) != initial_problem_count:
        return None
    return MeasurementArray(
        dtype="complex128",
        unit=_FAKE_RESPONSE_UNIT,
        shape=[len(frames)],
        values=[
            ComplexQuantity(
                real=value.real,
                imag=value.imag,
                unit=_FAKE_RESPONSE_UNIT,
            )
            for value in complex_values
        ],
    )


def _realize_raw_trace_value(
    selected_output: SelectedFakeMeasurementOutput,
    frames: tuple[CorrelatedFakeListFrame, ...],
    *,
    result_index: int,
    problems: list[Problem],
) -> MeasurementArray | None:
    initial_problem_count = len(problems)
    result = selected_output.result
    details = _realization_identity_details(result)
    path = ("results", result_index)
    window = selected_output.acquisition_window
    trace_values: list[list[ComplexQuantity]] = []
    for shot_index, frame in enumerate(frames):
        frame_path = (*path, "frames", shot_index)
        if frame.shot_index != shot_index:
            problems.append(
                _raw_trace_realization_problem(
                    "fake_raw_trace_shot_identity_mismatch",
                    "fake raw-trace frames must retain contiguous shot identity; "
                    f"expected {shot_index}, got {frame.shot_index}",
                    path=(*frame_path, "shot_index"),
                    details={
                        **details,
                        "expected": shot_index,
                        "actual": frame.shot_index,
                    },
                )
            )
        if frame.frame.kind is not AcquisitionKind.RAW_TRACE:
            problems.append(
                _raw_trace_realization_problem(
                    "fake_raw_trace_frame_kind_mismatch",
                    "fake raw-trace realization cannot accept acquisition kind "
                    f"{frame.frame.kind.value!r}",
                    path=(*frame_path, "kind"),
                    details={
                        **details,
                        "expected": AcquisitionKind.RAW_TRACE.value,
                        "actual": frame.frame.kind.value,
                    },
                )
            )
            continue
        raw_value = cast("tuple[complex, ...]", frame.frame.value)
        if len(raw_value) != window.sample_count:
            problems.append(
                _raw_trace_realization_problem(
                    "fake_raw_trace_frame_shape_mismatch",
                    "fake raw-trace frames must contain exactly "
                    f"{window.sample_count} samples",
                    path=(*frame_path, "value"),
                    details={
                        **details,
                        "expected": window.sample_count,
                        "actual": len(raw_value),
                    },
                )
            )
            continue
        trace_values.append(
            [
                ComplexQuantity(
                    real=sample.real,
                    imag=sample.imag,
                    unit=_FAKE_RESPONSE_UNIT,
                )
                for sample in raw_value
            ]
        )
    if len(problems) != initial_problem_count:
        return None
    return MeasurementArray(
        dtype="complex128",
        unit=_FAKE_RESPONSE_UNIT,
        shape=[len(frames), window.sample_count],
        values=list[object](trace_values),
    )


@dataclass(frozen=True, slots=True)
class _PreparedAcquisition:
    list_index: int
    program_id: PulseProgramId
    event_id: PulseEventId
    signal: AcquireSignal
    kind: AcquisitionKind
    start_seconds: Decimal
    duration_seconds: Decimal


@dataclass(frozen=True, slots=True)
class _ArtifactAcquisition:
    list_index: int
    program_id: PulseProgramId
    window: FakeAcquisitionWindow


def _select_fake_measurement_outputs(
    compiled_target: _FakeListCompiledTarget,
    target: FakeListTarget,
    bindings: tuple[FakeMeasurementRealizationBinding, ...],
) -> tuple[SelectedFakeMeasurementOutput, ...]:
    mapping = compiled_target.mapping.domain_mapping
    compiled = compiled_target.compiled
    artifact = compiled.artifact
    expected_addresses = {result.result_address for result in mapping.results}
    binding_by_address: dict[
        TargetAcquisitionAddress,
        FakeMeasurementRealizationBinding,
    ] = {}
    problems: list[Problem] = []
    target_mismatch = False
    for field_name, expected, actual in (
        ("target_id", compiled.target_id, target.id),
        (
            "capability_fingerprint",
            compiled.capability_fingerprint,
            target.capability_fingerprint,
        ),
    ):
        if actual == expected:
            continue
        target_mismatch = True
        problems.append(
            _target_selection_problem(
                "fake_measurement_target_mismatch",
                f"selected target {field_name} does not match compiled request",
                path=("target", field_name),
                details={
                    "field": field_name,
                    "expected": _problem_fact(expected),
                    "actual": _problem_fact(actual),
                },
            )
        )
    if not target_mismatch and artifact.sample_rate_hz != target.sample_rate_hz:
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_artifact_capability_mismatch",
                "compiled artifact sample rate does not match the selected target",
                path=("artifact", "sample_rate_hz"),
                details={
                    "field": "sample_rate_hz",
                    "expected": target.sample_rate_hz,
                    "actual": artifact.sample_rate_hz,
                },
            )
        )
    for binding_index, binding in enumerate(bindings):
        address = binding.result_address
        if address in binding_by_address:
            problems.append(
                _binding_selection_problem(
                    "fake_measurement_realization_binding_duplicate",
                    f"result address {address!r} has more than one realization policy",
                    category=ProblemCategory.CONFLICT,
                    path=("bindings", binding_index, "result_address"),
                    details={"result_address": repr(address)},
                )
            )
            continue
        binding_by_address[address] = binding
        if address not in expected_addresses:
            problems.append(
                _binding_selection_problem(
                    "fake_measurement_realization_binding_unknown",
                    f"result address {address!r} is not in the compiled mapping",
                    category=ProblemCategory.INVALID_INPUT,
                    path=("bindings", binding_index, "result_address"),
                    details={"result_address": repr(address)},
                )
            )
    for result_index, result in enumerate(mapping.results):
        if result.result_address not in binding_by_address:
            problems.append(
                _binding_selection_problem(
                    "fake_measurement_realization_binding_missing",
                    "result address "
                    f"{result.result_address!r} has no realization policy",
                    category=ProblemCategory.INVALID_INPUT,
                    path=("results", result_index, "result_address"),
                    details=_realization_identity_details(result),
                )
            )

    prepared = _prepared_acquisitions(compiled_target)
    artifact_acquisitions = _artifact_acquisitions(compiled_target)
    if set(prepared) != expected_addresses:
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_prepared_acquisition_coverage_mismatch",
                "prepared acquisition inventory does not cover the result mapping",
                path=("prepared_acquisitions",),
                details={
                    "expected_count": len(expected_addresses),
                    "actual_count": len(prepared),
                },
            )
        )
    if set(artifact_acquisitions) != expected_addresses:
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_artifact_acquisition_coverage_mismatch",
                "compiled artifact acquisition inventory does not cover the "
                "result mapping",
                path=("artifact", "acquisitions"),
                details={
                    "expected_count": len(expected_addresses),
                    "actual_count": len(artifact_acquisitions),
                },
            )
        )
    if problems:
        raise CheckFailed(problems)

    selected_outputs: list[SelectedFakeMeasurementOutput] = []
    for result_index, result in enumerate(mapping.results):
        initial_problem_count = len(problems)
        address = result.result_address
        binding = binding_by_address[address]
        prepared_acquisition = prepared[address]
        artifact_acquisition = artifact_acquisitions[address]
        problems.extend(
            _artifact_acquisition_problems(
                result,
                prepared=prepared_acquisition,
                compiled=artifact_acquisition,
                target=target,
                result_index=result_index,
            )
        )
        expected_kind = _acquisition_kind_for_realization(binding.kind)
        if prepared_acquisition.kind is not expected_kind:
            code = (
                "fake_integrated_iq_acquisition_kind_mismatch"
                if binding.kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS
                else "fake_raw_trace_acquisition_kind_mismatch"
            )
            problems.append(
                _policy_selection_problem(
                    binding.kind,
                    code,
                    f"selected {binding.kind.value!r} policy cannot accept "
                    f"acquisition kind {prepared_acquisition.kind.value!r}",
                    path=("results", result_index, "acquisition", "kind"),
                    details={
                        **_realization_identity_details(result),
                        "expected": expected_kind.value,
                        "actual": prepared_acquisition.kind.value,
                    },
                )
            )
        problems.extend(
            _product_policy_problems(
                result,
                binding.kind,
                repetitions=compiled_target.compiled.repetitions,
                sample_count=artifact_acquisition.window.sample_count,
                result_index=result_index,
            )
        )
        if len(problems) == initial_problem_count:
            selected_outputs.append(
                SelectedFakeMeasurementOutput(
                    result,
                    compiled_target.mapping.batch.acquisition_origin_for(address),
                    artifact_acquisition.window,
                    binding.kind,
                )
            )
    if problems:
        raise CheckFailed(problems)
    return tuple(selected_outputs)


def _prepared_acquisitions(
    compiled_target: _FakeListCompiledTarget,
) -> dict[TargetAcquisitionAddress, _PreparedAcquisition]:
    prepared: dict[TargetAcquisitionAddress, _PreparedAcquisition] = {}
    for list_index, entry in enumerate(compiled_target.mapping.batch.request.entries):
        slots_by_id = {slot.id: slot for slot in entry.program.acquisition_slots}
        for event in entry.program.events:
            instruction = event.instruction
            if not isinstance(instruction, Acquire):
                continue
            slot = slots_by_id.get(instruction.slot_id)
            if slot is None:
                msg = "prepared target acquisition event references an unknown slot"
                raise ValueError(msg)
            address = TargetAcquisitionAddress(
                entry_id=entry.id,
                slot_id=instruction.slot_id,
            )
            if address in prepared:
                msg = "prepared target contains duplicate acquisition addresses"
                raise ValueError(msg)
            prepared[address] = _PreparedAcquisition(
                list_index=list_index,
                program_id=entry.program.id,
                event_id=event.id,
                signal=instruction.signal,
                kind=slot.kind,
                start_seconds=event.start_seconds,
                duration_seconds=event.duration_seconds,
            )
    return prepared


def _artifact_acquisitions(
    compiled_target: _FakeListCompiledTarget,
) -> dict[TargetAcquisitionAddress, _ArtifactAcquisition]:
    artifact = compiled_target.compiled.artifact
    acquisitions: dict[TargetAcquisitionAddress, _ArtifactAcquisition] = {}
    for entry in artifact.entries:
        for window in entry.acquisitions:
            address = TargetAcquisitionAddress(
                entry_id=entry.entry_id,
                slot_id=window.slot_id,
            )
            if address in acquisitions:
                msg = "fake list artifact contains duplicate acquisition addresses"
                raise ValueError(msg)
            acquisitions[address] = _ArtifactAcquisition(
                list_index=entry.list_index,
                program_id=entry.program_id,
                window=window,
            )
    return acquisitions


def _artifact_acquisition_problems(
    result: DomainMappedResult[TargetCompileEntryId, TargetAcquisitionAddress],
    *,
    prepared: _PreparedAcquisition,
    compiled: _ArtifactAcquisition,
    target: FakeListTarget,
    result_index: int,
) -> list[Problem]:
    details = _realization_identity_details(result)
    path = ("results", result_index, "artifact", "acquisition")
    expected_start = _exact_sample_index(
        prepared.start_seconds,
        target.sample_rate_hz,
    )
    expected_count = _exact_sample_index(
        prepared.duration_seconds,
        target.sample_rate_hz,
    )
    facts: tuple[tuple[str, object, object], ...] = (
        ("list_index", prepared.list_index, compiled.list_index),
        ("program_id", prepared.program_id, compiled.program_id),
        ("event_id", prepared.event_id, compiled.window.event_id),
        ("signal", prepared.signal, compiled.window.signal),
        ("kind", prepared.kind, compiled.window.kind),
        (
            "channel_id",
            target.acquisition_channel(prepared.signal),
            compiled.window.channel_id,
        ),
        ("start_sample", expected_start, compiled.window.start_sample),
        ("sample_count", expected_count, compiled.window.sample_count),
    )
    problems: list[Problem] = []
    for field_name, expected, actual in facts:
        if expected == actual:
            continue
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_artifact_acquisition_mismatch",
                "compiled acquisition window does not match prepared "
                f"{field_name}: {actual!r} != {expected!r}",
                path=(*path, field_name),
                details={
                    **details,
                    "field": field_name,
                    "expected": _problem_fact(expected),
                    "actual": _problem_fact(actual),
                },
            )
        )
    return problems


def _product_policy_problems(
    result: DomainMappedResult[TargetCompileEntryId, TargetAcquisitionAddress],
    kind: FakeMeasurementRealizationKind,
    *,
    repetitions: int,
    sample_count: int,
    result_index: int,
) -> list[Problem]:
    product = _mapped_result_product(result)
    details = _realization_identity_details(result)
    path = ("results", result_index, "product")
    prefix = (
        "fake_integrated_iq"
        if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS
        else "fake_raw_trace"
    )
    label = (
        "integrated-IQ"
        if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS
        else "raw-trace"
    )
    problems: list[Problem] = []
    for field_name, expected, actual in (
        ("kind", "observable", product.kind),
        ("dtype", "complex128", product.dtype),
        ("unit", _FAKE_RESPONSE_UNIT, product.unit),
    ):
        if actual == expected:
            continue
        problems.append(
            _policy_selection_problem(
                kind,
                f"{prefix}_product_{field_name}_mismatch",
                f"fake {label} realization requires {field_name} "
                f"{expected!r}, got {actual!r}",
                path=(*path, field_name),
                details={
                    **details,
                    "expected": expected,
                    "actual": actual,
                },
            )
        )

    expected_axis_count = (
        1 if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS else 2
    )
    if len(product.axes) != expected_axis_count:
        problems.append(
            _policy_selection_problem(
                kind,
                f"{prefix}_product_axes_mismatch",
                f"fake {label} realization requires {expected_axis_count} "
                f"axes, got {len(product.axes)}",
                path=(*path, "axes"),
                details={
                    **details,
                    "expected_axis_count": expected_axis_count,
                    "actual_axis_count": len(product.axes),
                },
            )
        )
        return problems

    shot_axis = product.axes[0]
    if shot_axis.id != "shot" or shot_axis.kind != "shot" or shot_axis.unit != "count":
        problems.append(
            _policy_selection_problem(
                kind,
                f"{prefix}_shot_axis_mismatch",
                f"fake {label} realization requires canonical shot/count first",
                path=(*path, "axes", 0),
                details={
                    **details,
                    "expected": "shot/shot/count",
                    "actual": f"{shot_axis.id}/{shot_axis.kind}/{shot_axis.unit}",
                },
            )
        )
    if shot_axis.size != repetitions:
        problems.append(
            _policy_selection_problem(
                kind,
                f"{prefix}_shot_count_mismatch",
                "product shot axis size does not match target repetitions: "
                f"{shot_axis.size} != {repetitions}",
                path=(*path, "axes", 0, "size"),
                details={
                    **details,
                    "expected": repetitions,
                    "actual": shot_axis.size,
                },
            )
        )
    if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS:
        return problems

    sample_axis = product.axes[1]
    if (
        sample_axis.id != "sample"
        or sample_axis.kind != "sample"
        or sample_axis.unit != "count"
    ):
        problems.append(
            _raw_trace_selection_problem(
                "fake_raw_trace_sample_axis_mismatch",
                "fake raw-trace realization requires canonical sample/count second",
                path=(*path, "axes", 1),
                details={
                    **details,
                    "expected": "sample/sample/count",
                    "actual": f"{sample_axis.id}/{sample_axis.kind}/{sample_axis.unit}",
                },
            )
        )
    if sample_axis.size != sample_count:
        problems.append(
            _raw_trace_selection_problem(
                "fake_raw_trace_sample_count_mismatch",
                "product sample axis size does not match the compiled acquisition "
                f"window: {sample_axis.size} != {sample_count}",
                path=(*path, "axes", 1, "size"),
                details={
                    **details,
                    "expected": sample_count,
                    "actual": sample_axis.size,
                },
            )
        )
    return problems


def _policy_selection_problem(
    kind: FakeMeasurementRealizationKind,
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS:
        return _selection_problem(code, message, path=path, details=details)
    return _raw_trace_selection_problem(code, message, path=path, details=details)


def _acquisition_kind_for_realization(
    kind: FakeMeasurementRealizationKind,
) -> AcquisitionKind:
    if kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS:
        return AcquisitionKind.INTEGRATED_IQ
    return AcquisitionKind.RAW_TRACE


def _exact_sample_index(seconds: Decimal, sample_rate_hz: int) -> int | None:
    scaled = seconds * Decimal(sample_rate_hz)
    integral = scaled.to_integral_value()
    return int(integral) if scaled == integral else None


def _problem_fact(value: object) -> str | int | None:
    return value if isinstance(value, int | str) or value is None else repr(value)


def _require_shot_index(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = "fake-list shot index must be an integer"
        raise TypeError(msg)
    if value < 0:
        msg = "fake-list shot index must be non-negative"
        raise ValueError(msg)


def _mapped_result_product(
    result: DomainMappedResult[TargetCompileEntryId, TargetAcquisitionAddress],
) -> DomainProductContractView:
    product_uses = result.product_uses
    if not product_uses:
        raise AssertionError("mapped fake results require a logical product use")
    product = product_uses[0].product
    if any(product_use.product is not product for product_use in product_uses[1:]):
        raise AssertionError("mapped fake result fan-out changed product contract")
    return product


def _realization_identity_details(
    result: DomainMappedResult[TargetCompileEntryId, TargetAcquisitionAddress],
) -> dict[str, object]:
    product = _mapped_result_product(result)
    return {
        "logical_point_id": result.point.id,
        "product_use_ids": [product_use.id for product_use in result.product_uses],
        "product_id": product.id,
    }


def _realization_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("fake_integrated_iq_realization", *path),
        details=details,
    )


def _selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.UNAVAILABLE,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


def _binding_selection_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


def _target_selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.CONFLICT,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


def _raw_trace_realization_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("fake_raw_trace_realization", *path),
        details=details,
    )


def _raw_trace_selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.UNAVAILABLE,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_raw_trace_realization", *path),
        details=details,
    )


def _artifact_selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


__all__ = [
    "CorrelatedFakeListFrame",
    "CorrelatedFakeListRun",
    "FakeMeasurementRealizationBinding",
    "FakeMeasurementRealizationKind",
    "RealizedFakeMeasurementRun",
    "SelectedFakeMeasurementOutput",
    "SelectedFakeMeasurementRealization",
    "correlate_fake_list_run",
    "execute_correlated_fake_list",
    "execute_realized_fake_measurements",
    "integrated_iq_shots",
    "raw_trace_shots",
    "realize_fake_measurements",
    "select_fake_measurement_realization",
]
