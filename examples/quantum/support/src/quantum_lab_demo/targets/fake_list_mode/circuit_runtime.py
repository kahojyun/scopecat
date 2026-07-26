"""Correlate fake target evidence to Scopecat logical quantum outputs.

The ordinary fake-list runtime remains usable as a target-specific component.
This adapter correlates a mapped target artifact, its raw run, and every
returned frame.
Frames remain raw target evidence after correlation and are then projected to
the integrated-IQ result contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

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
from scopecat_quantum.program_results import (
    MappedQuantumTarget,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetResultAddress,
)

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeListArtifact,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeDigitizerFrame,
    FakeListRun,
)

_FAKE_RESPONSE_UNIT = "ratio"

type _MappedFakeListTarget = MappedQuantumTarget[FakeListArtifact]


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
    """Canonically ordered raw target data after correlation."""

    mapped_target: _MappedFakeListTarget
    target_run: FakeListRun
    frames: tuple[CorrelatedFakeListFrame, ...]


def correlate_fake_list_run(
    mapped_target: _MappedFakeListTarget,
    target_run: FakeListRun,
) -> CorrelatedFakeListRun:
    """Correlate one raw fake run without interpreting values."""

    mapping = mapped_target.mapping
    artifact = mapped_target.artifact
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
        (_single_acquisition_address(result.result_address), shot_index)
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    }
    if set(raw_by_address_shot) != expected_keys:
        msg = (
            "fake-list frames must exactly cover every mapped acquisition for "
            "every shot"
        )
        raise ValueError(msg)

    correlated_frames = tuple(
        CorrelatedFakeListFrame(
            frame=raw_by_address_shot[
                (
                    _single_acquisition_address(result.result_address),
                    shot_index,
                )
            ],
            mapped_result=result,
        )
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    )
    return CorrelatedFakeListRun(
        mapped_target,
        target_run,
        correlated_frames,
    )


def realize_fake_measurements(
    correlated_run: CorrelatedFakeListRun,
) -> tuple[DomainResultValue[TargetResultAddress], ...]:
    """Project one correlated run to canonical integrated-IQ values."""

    candidates: list[DomainResultValue[TargetResultAddress]] = []
    problems: list[Problem] = []
    for result_index, result in enumerate(correlated_run.mapped_target.mapping.results):
        frames = _frames_for_result_address(correlated_run, result.result_address)
        value = _realize_integrated_iq_value(
            result,
            frames,
            result_index=result_index,
            problems=problems,
        )
        if value is not None:
            candidates.append(DomainResultValue(result.result_address, value))
    if problems:
        raise ProviderContractError(problems)

    return tuple(candidates)


def _frames_for_result_address(
    correlated_run: CorrelatedFakeListRun,
    result_address: TargetResultAddress,
) -> tuple[CorrelatedFakeListFrame, ...]:
    address = _single_acquisition_address(result_address)
    return tuple(frame for frame in correlated_run.frames if frame.address == address)


def _realize_integrated_iq_value(
    result: DomainMappedResult[TargetResultAddress],
    frames: tuple[CorrelatedFakeListFrame, ...],
    *,
    result_index: int,
    problems: list[Problem],
) -> MeasurementArray | None:
    initial_problem_count = len(problems)
    details = _realization_identity_details(result)
    path = ("results", result_index)
    address = _single_acquisition_address(result.result_address)
    values_by_frame: dict[tuple[int, TargetAcquisitionAddress], ComplexQuantity] = {}
    for frame_index, frame in enumerate(frames):
        expected_shot = frame_index
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
    shot_count = len(frames)
    return MeasurementArray(
        dtype="complex128",
        unit=_FAKE_RESPONSE_UNIT,
        shape=[shot_count],
        values=[
            values_by_frame[(shot_index, address)] for shot_index in range(shot_count)
        ],
    )


def validate_fake_measurement_mapping(
    mapped_target: _MappedFakeListTarget,
) -> None:
    """Require the logical result shapes consumed by fake IQ realization."""

    problems: list[Problem] = []
    for result_index, result in enumerate(mapped_target.mapping.results):
        problems.extend(
            _product_problems(
                result,
                repetitions=mapped_target.artifact.repetitions,
                result_index=result_index,
            )
        )
    if problems:
        raise CheckFailed(problems)


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

    _single_acquisition_address(result.result_address)
    expected_axis_count = 1
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
    return problems


def _single_acquisition_address(
    address: TargetResultAddress,
) -> TargetAcquisitionAddress:
    if not isinstance(address, TargetAcquisitionAddress):
        raise ValueError("fake list-mode results require one acquisition address")
    return address


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


__all__ = [
    "CorrelatedFakeListFrame",
    "CorrelatedFakeListRun",
    "correlate_fake_list_run",
    "realize_fake_measurements",
    "validate_fake_measurement_mapping",
]
