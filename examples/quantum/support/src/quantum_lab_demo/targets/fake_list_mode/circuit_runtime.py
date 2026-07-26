"""Correlate fake target evidence to Scopecat logical quantum outputs.

The ordinary fake-list runtime remains usable as a target-specific component.
This adapter layer additionally proves that a compiled logical circuit or
mixed gate/pulse batch, its raw run, and every returned frame belong to the
same transient mapping chain.
Frames remain raw target evidence after correlation and are then projected to
the integrated-IQ result contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.measurements.results import ComplexQuantity, MeasurementArray
from scopecat.sdk.domain import (
    DomainMappedResult,
    DomainPointRef,
    DomainProductContractView,
    DomainProductUseRef,
    DomainResultValue,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat_quantum._ids import PulseEventId, PulseProgramId
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
)
from scopecat_quantum.program_targets import QuantumTargetAcquisitionOrigin
from scopecat_quantum.pulses import Acquire, AcquireSignal
from scopecat_quantum.result_collections import (
    ResultCollection,
    result_collection_axes,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetResultAddress,
    target_result_acquisition_addresses,
)

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeListArtifact,
    FakeListTarget,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeDigitizerFrame,
    FakeListRun,
)

_FAKE_RESPONSE_UNIT = "ratio"

type _FakeListCompiledTarget = CompiledQuantumTarget[FakeListArtifact]
type _FakeListAcquisitionOrigin = QuantumTargetAcquisitionOrigin


@dataclass(frozen=True, slots=True)
class CorrelatedFakeListFrame:
    """One raw fake frame related to exact quantum and SDK identities."""

    frame: FakeDigitizerFrame
    mapped_result: DomainMappedResult[TargetResultAddress] = field(repr=False)

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


@dataclass(frozen=True, slots=True)
class CorrelatedFakeListRun:
    """Checked, canonically ordered fake target evidence."""

    compiled_target: _FakeListCompiledTarget
    target_run: FakeListRun
    frames: tuple[CorrelatedFakeListFrame, ...]


@dataclass(frozen=True, slots=True, init=False)
class SelectedFakeMeasurementOutput:
    """One mapped result validated against its compiled acquisition inventory."""

    result: DomainMappedResult[TargetResultAddress] = field(repr=False)

    def __init__(
        self,
        result: DomainMappedResult[TargetResultAddress],
        acquisition_origins: tuple[_FakeListAcquisitionOrigin, ...],
        acquisition_windows: tuple[FakeAcquisitionWindow, ...],
    ) -> None:
        addresses = target_result_acquisition_addresses(result.result_address)
        if tuple(origin.address for origin in acquisition_origins) != addresses:
            msg = "selected fake output origins must cover its physical result tree"
            raise ValueError(msg)
        if tuple(window.slot_id for window in acquisition_windows) != tuple(
            address.slot_id for address in addresses
        ):
            msg = "selected fake output windows must cover its physical result tree"
            raise ValueError(msg)
        object.__setattr__(self, "result", result)

    @property
    def result_address(self) -> TargetResultAddress:
        return self.result.result_address

    @property
    def point(self) -> DomainPointRef:
        return self.result.point

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self.result.product_uses


@dataclass(frozen=True, slots=True, init=False)
class SelectedFakeMeasurementRealization:
    """Exact pre-effect closure of fake measurement inputs."""

    compiled_target: _FakeListCompiledTarget = field(repr=False)
    target: FakeListTarget = field(repr=False)
    outputs: tuple[SelectedFakeMeasurementOutput, ...]

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
        if len({output.result_address for output in selected_outputs}) != len(
            selected_outputs
        ):
            msg = "selected fake measurement outputs require unique result addresses"
            raise ValueError(msg)
        object.__setattr__(self, "compiled_target", compiled_target)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "outputs", selected_outputs)


def select_fake_measurement_realization(
    compiled_target: _FakeListCompiledTarget,
    target: FakeListTarget,
) -> SelectedFakeMeasurementRealization:
    """Seal compiled result inputs before target effects."""

    selected_outputs = _select_fake_measurement_outputs(
        compiled_target,
        target,
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
        (address, shot_index)
        for result in mapping.results
        for address in target_result_acquisition_addresses(result.result_address)
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
            frame=raw_by_address_shot[(address, shot_index)],
            mapped_result=result,
        )
        for result in mapping.results
        for shot_index in range(compiled.repetitions)
        for address in target_result_acquisition_addresses(result.result_address)
    )
    return CorrelatedFakeListRun(
        compiled_target,
        target_run,
        correlated_frames,
    )


def realize_fake_measurements(
    selection: SelectedFakeMeasurementRealization,
    correlated_run: CorrelatedFakeListRun,
) -> tuple[DomainResultValue[TargetResultAddress], ...]:
    """Project one correlated run to canonical integrated-IQ values."""

    if selection.compiled_target is not correlated_run.compiled_target:
        msg = "fake measurement realization requires the selected compiled target"
        raise ValueError(msg)

    candidates: list[DomainResultValue[TargetResultAddress]] = []
    problems: list[Problem] = []
    for result_index, selected_output in enumerate(selection.outputs):
        frames = _frames_for_result_address(
            correlated_run, selected_output.result_address
        )
        value = _realize_integrated_iq_value(
            selected_output,
            frames,
            result_index=result_index,
            problems=problems,
        )
        if value is not None:
            candidates.append(DomainResultValue(selected_output.result_address, value))
    if problems:
        raise ProviderContractError(problems)

    return tuple(candidates)


def _frames_for_result_address(
    correlated_run: CorrelatedFakeListRun,
    result_address: TargetResultAddress,
) -> tuple[CorrelatedFakeListFrame, ...]:
    addresses = set(target_result_acquisition_addresses(result_address))
    return tuple(frame for frame in correlated_run.frames if frame.address in addresses)


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
    addresses = target_result_acquisition_addresses(result.result_address)
    values_by_frame: dict[tuple[int, TargetAcquisitionAddress], ComplexQuantity] = {}
    for frame_index, frame in enumerate(frames):
        expected_shot = frame_index // len(addresses)
        frame_path = (*path, "frames", frame_index)
        if frame.shot_index != expected_shot:
            problems.append(
                _realization_problem(
                    "fake_integrated_iq_shot_identity_mismatch",
                    "fake integrated-IQ frames must retain contiguous shot "
                    f"identity; expected {expected_shot}, got {frame.shot_index}",
                    path=(*frame_path, "shot_index"),
                    details={
                        **details,
                        "expected": expected_shot,
                        "actual": frame.shot_index,
                    },
                )
            )
        value = frame.frame.value
        values_by_frame[(frame.shot_index, frame.address)] = ComplexQuantity(
            real=value.real,
            imag=value.imag,
            unit=_FAKE_RESPONSE_UNIT,
        )
    if len(problems) != initial_problem_count:
        return None
    shot_count = len(frames) // len(addresses)
    return MeasurementArray(
        dtype="complex128",
        unit=_FAKE_RESPONSE_UNIT,
        shape=[
            shot_count,
            *(size for _axis_id, size in result_collection_axes(result.result_address)),
        ],
        values=[
            _result_collection_values(
                result.result_address,
                {
                    address: values_by_frame[(shot_index, address)]
                    for address in addresses
                },
            )
            for shot_index in range(shot_count)
        ],
    )


def _result_collection_values(
    address: TargetResultAddress,
    values_by_address: Mapping[TargetAcquisitionAddress, object],
) -> object:
    if not isinstance(address, ResultCollection):
        return values_by_address[address]
    return [
        _result_collection_values(item, values_by_address) for item in address.items
    ]


@dataclass(frozen=True, slots=True)
class _PreparedAcquisition:
    list_index: int
    program_id: PulseProgramId
    event_id: PulseEventId
    signal: AcquireSignal
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
) -> tuple[SelectedFakeMeasurementOutput, ...]:
    mapping = compiled_target.mapping.domain_mapping
    compiled = compiled_target.compiled
    artifact = compiled.artifact
    expected_acquisition_addresses = {
        address
        for result in mapping.results
        for address in target_result_acquisition_addresses(result.result_address)
    }
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

    prepared = _prepared_acquisitions(compiled_target)
    artifact_acquisitions = _artifact_acquisitions(compiled_target)
    if set(prepared) != expected_acquisition_addresses:
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_prepared_acquisition_coverage_mismatch",
                "prepared acquisition inventory does not cover the result mapping",
                path=("prepared_acquisitions",),
                details={
                    "expected_count": len(expected_acquisition_addresses),
                    "actual_count": len(prepared),
                },
            )
        )
    if set(artifact_acquisitions) != expected_acquisition_addresses:
        problems.append(
            _artifact_selection_problem(
                "fake_measurement_artifact_acquisition_coverage_mismatch",
                "compiled artifact acquisition inventory does not cover the "
                "result mapping",
                path=("artifact", "acquisitions"),
                details={
                    "expected_count": len(expected_acquisition_addresses),
                    "actual_count": len(artifact_acquisitions),
                },
            )
        )
    if problems:
        raise CheckFailed(problems)

    selected_outputs: list[SelectedFakeMeasurementOutput] = []
    for result_index, result in enumerate(mapping.results):
        initial_problem_count = len(problems)
        result_address = result.result_address
        addresses = target_result_acquisition_addresses(result_address)
        selected_prepared = tuple(prepared[address] for address in addresses)
        selected_artifacts = tuple(
            artifact_acquisitions[address] for address in addresses
        )
        for prepared_acquisition, artifact_acquisition in zip(
            selected_prepared,
            selected_artifacts,
            strict=True,
        ):
            problems.extend(
                _artifact_acquisition_problems(
                    result,
                    prepared=prepared_acquisition,
                    compiled=artifact_acquisition,
                    target=target,
                    result_index=result_index,
                )
            )
        problems.extend(
            _product_problems(
                result,
                repetitions=compiled_target.compiled.repetitions,
                result_index=result_index,
            )
        )
        if len(problems) == initial_problem_count:
            selected_outputs.append(
                SelectedFakeMeasurementOutput(
                    result,
                    tuple(
                        compiled_target.mapping.batch.acquisition_origin_for(address)
                        for address in addresses
                    ),
                    tuple(item.window for item in selected_artifacts),
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
    result: DomainMappedResult[TargetResultAddress],
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


def _product_problems(
    result: DomainMappedResult[TargetResultAddress],
    *,
    repetitions: int,
    result_index: int,
) -> list[Problem]:
    product = _mapped_result_product(result)
    details = _realization_identity_details(result)
    path = ("results", result_index, "product")
    problems: list[Problem] = []
    for field_name, expected, actual in (
        ("dtype", "complex128", product.dtype),
        ("unit", _FAKE_RESPONSE_UNIT, product.unit),
    ):
        if actual == expected:
            continue
        problems.append(
            _selection_problem(
                f"fake_integrated_iq_product_{field_name}_mismatch",
                f"fake integrated-IQ realization requires {field_name} "
                f"{expected!r}, got {actual!r}",
                path=(*path, field_name),
                details={
                    **details,
                    "expected": expected,
                    "actual": actual,
                },
            )
        )

    collection_axes = result_collection_axes(result.result_address)
    expected_axis_count = 1 + len(collection_axes)
    if len(product.axes) != expected_axis_count:
        problems.append(
            _selection_problem(
                "fake_integrated_iq_product_axes_mismatch",
                f"fake integrated-IQ realization requires {expected_axis_count} "
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
            _selection_problem(
                "fake_integrated_iq_shot_axis_mismatch",
                "fake integrated-IQ realization requires canonical shot/count first",
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
            _selection_problem(
                "fake_integrated_iq_shot_count_mismatch",
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
    for offset, ((axis_id, axis_size), product_axis) in enumerate(
        zip(collection_axes, product.axes[1:], strict=False),
        start=1,
    ):
        if product_axis.id == axis_id and product_axis.size == axis_size:
            continue
        problems.append(
            _selection_problem(
                "fake_integrated_iq_collection_axis_mismatch",
                f"fake integrated-IQ result tree requires axis {axis_id!r} "
                f"of size {axis_size}",
                path=(*path, "axes", offset),
                details={
                    **details,
                    "expected": f"{axis_id}/{axis_size}",
                    "actual": f"{product_axis.id}/{product_axis.size}",
                },
            )
        )
    return problems


def _exact_sample_index(seconds: Decimal, sample_rate_hz: int) -> int | None:
    scaled = seconds * Decimal(sample_rate_hz)
    integral = scaled.to_integral_value()
    return int(integral) if scaled == integral else None


def _problem_fact(value: object) -> str | int | None:
    return value if isinstance(value, int | str) or value is None else repr(value)


def _mapped_result_product(
    result: DomainMappedResult[TargetResultAddress],
) -> DomainProductContractView:
    product_uses = result.product_uses
    if not product_uses:
        raise AssertionError("mapped fake results require a logical product use")
    product = product_uses[0].product
    if any(product_use.product is not product for product_use in product_uses[1:]):
        raise AssertionError("mapped fake result fan-out changed product contract")
    return product


def _realization_identity_details(
    result: DomainMappedResult[TargetResultAddress],
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
    return problem(
        code,
        message,
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
    return problem(
        code,
        message,
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
    return problem(
        code,
        message,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


def _artifact_selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PLANNING,
        location=model_location("fake_measurement_realization", *path),
        details=details,
    )


__all__ = [
    "CorrelatedFakeListFrame",
    "CorrelatedFakeListRun",
    "SelectedFakeMeasurementOutput",
    "SelectedFakeMeasurementRealization",
    "correlate_fake_list_run",
    "realize_fake_measurements",
    "select_fake_measurement_realization",
]
