from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast, override

import pytest

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.errors import CheckFailed, MeasurementTransformExecutionError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import ProductUse
from scopecat.measurements.host_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformImplementation,
    HostMeasurementTransformKernel,
    HostMeasurementTransformValidator,
    bind_host_measurement_transforms,
    execute_host_measurement_transforms,
)
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    MeasurementTransformInputPort,
    MeasurementTransformOutputPort,
    NativeMeasurementTransformId,
)
from scopecat.measurements.values import seal_measurement_values
from scopecat.records.measurement import MeasurementArray, MeasurementValue
from scopecat.records.parameter import Quantity
from tests.testkit.measurement_assembly import (
    MeasurementAssemblyScenario,
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def _product(scenario: MeasurementAssemblyScenario, use: ProductUse) -> ProductDef:
    products = {
        product.id: product
        for product in scenario.linked_points.linked_plan.program.product_defs
    }
    return products[use.product_id]


def _input_port(
    scenario: MeasurementAssemblyScenario,
    port_id: str,
    use: ProductUse,
) -> MeasurementTransformInputPort:
    return MeasurementTransformInputPort(
        id=port_id,
        product_use_id=use.id,
        product=_product(scenario, use),
    )


def _output_port(
    scenario: MeasurementAssemblyScenario,
    port_id: str,
    use: ProductUse,
) -> MeasurementTransformOutputPort:
    return MeasurementTransformOutputPort(
        id=port_id,
        product_use_ids=(use.id,),
        product=_product(scenario, use),
    )


def _semantic(name: str) -> MeasurementTransformSemanticContract:
    return MeasurementTransformSemanticContract(
        id=name,
        version="1",
        parameters={"policy": name},
    )


def _transform(
    scenario: MeasurementAssemblyScenario,
    transform_id: str,
    inputs: tuple[tuple[str, ProductUse], ...],
    outputs: tuple[tuple[str, ProductUse], ...],
    *,
    semantic_id: str | None = None,
) -> MeasurementTransformDef:
    return MeasurementTransformDef(
        id=NativeMeasurementTransformId(transform_id),
        semantic=_semantic(semantic_id or transform_id),
        inputs=tuple(_input_port(scenario, name, use) for name, use in inputs),
        outputs=tuple(_output_port(scenario, name, use) for name, use in outputs),
    )


def _accept_transform(_transform: MeasurementTransformDef) -> None:
    return None


def _reject_transform(_transform: MeasurementTransformDef) -> None:
    raise ValueError("unsupported typed interface")


def _implementation(
    semantic_id: str,
    kernel: HostMeasurementTransformKernel,
    *,
    implementation_id: str | None = None,
    validator: HostMeasurementTransformValidator = _accept_transform,
) -> HostMeasurementTransformImplementation:
    return HostMeasurementTransformImplementation(
        id=implementation_id or f"host-{semantic_id}",
        validate_transform=validator,
        kernel=kernel,
    )


def _identity_kernel(
    call: HostMeasurementTransformCall,
) -> Mapping[str, Sequence[MeasurementValue]]:
    return {"output": call.inputs["input"]}


def _one_transform_plan(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
    kernel: HostMeasurementTransformKernel = _identity_kernel,
):
    scenario = measurement_assembly_scenario(point_values=point_values, use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "normalize",
        (("input", source),),
        (("output", output),),
        semantic_id="identity",
    )
    implementation = _implementation("identity", kernel)
    native_transforms = ((transform, implementation),)
    bound = bind_host_measurement_transforms(
        native_transforms,
        (source.id,),
    )
    source_values = measurement_value_candidates(scenario, (source,))
    return scenario, native_transforms, bound, source_values


def test_semantic_parameters_are_recursively_frozen_and_snapshot_inputs() -> None:
    parameters: dict[str, JsonValue] = {"nested": {"thresholds": [1.0, 2.0]}}
    semantic = MeasurementTransformSemanticContract(
        id="frozen",
        version="1",
        parameters=parameters,
    )
    nested_parameters = cast("dict[str, JsonValue]", parameters["nested"])
    thresholds = cast("list[JsonValue]", nested_parameters["thresholds"])
    thresholds.append(3.0)

    assert semantic.parameters["nested"] == {"thresholds": (1.0, 2.0)}
    nested = cast("dict[str, object]", semantic.parameters["nested"])
    with pytest.raises(TypeError, match="immutable"):
        nested["thresholds"] = ()


@pytest.mark.parametrize(
    ("semantic_id", "semantic_version"),
    (("", "1"), ("test.identity", "")),
)
def test_semantic_contract_requires_non_empty_identity(
    semantic_id: str,
    semantic_version: str,
) -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        MeasurementTransformSemanticContract(
            id=semantic_id,
            version=semantic_version,
        )


def test_semantic_contract_equality_is_order_independent() -> None:
    first = MeasurementTransformSemanticContract(
        id="test.identity",
        version="2",
        parameters={"z": [1, 2], "a": {"enabled": True}},
    )
    second = MeasurementTransformSemanticContract(
        id="test.identity",
        version="2",
        parameters={"a": {"enabled": True}, "z": [1, 2]},
    )

    assert first == second


def test_host_capability_validator_rejects_before_kernel() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "validated",
        (("input", source),),
        (("output", output),),
    )
    kernel_calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        nonlocal kernel_calls
        kernel_calls += 1
        return {"output": call.inputs["input"]}

    implementation = _implementation(
        "validated",
        kernel,
        validator=_reject_transform,
    )

    with pytest.raises(CheckFailed) as caught:
        bind_host_measurement_transforms(
            ((transform, implementation),),
            (source.id,),
        )

    assert caught.value.problems[0].code == (
        "measurement_transform_host_capability_rejected"
    )
    assert kernel_calls == 0


def test_binding_requires_unique_sources_covering_plan_inputs() -> None:
    scenario, native_transforms, _bound, _source = _one_transform_plan()
    source = scenario.uses[0]

    with pytest.raises(ValueError, match="cover graph inputs"):
        bind_host_measurement_transforms(native_transforms, ())
    with pytest.raises(ValueError, match="must be unique"):
        bind_host_measurement_transforms(
            native_transforms,
            (source.id, source.id),
        )


def test_point_runner_executes_multi_output_plan_in_compiler_order() -> None:
    scenario = measurement_assembly_scenario(use_count=4)
    source, left, right, result = scenario.uses
    split = _transform(
        scenario,
        "split",
        (("input", source),),
        (("left", left), ("right", right)),
    )
    combine = _transform(
        scenario,
        "combine",
        (("left", left), ("right", right)),
        (("output", result),),
    )
    calls: list[str] = []

    def split_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        calls.append(call.transform_id.value)
        values = call.inputs["input"]
        return {
            "left": tuple(values),
            "right": tuple(
                Quantity(value=value.value + 10.0, unit=value.unit)
                for value in values
                if isinstance(value, Quantity)
            ),
        }

    def combine_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        calls.append(call.transform_id.value)
        return {
            "output": tuple(
                Quantity(value=left.value + right.value, unit="ratio")
                for left, right in zip(
                    call.inputs["left"], call.inputs["right"], strict=True
                )
                if isinstance(left, Quantity) and isinstance(right, Quantity)
            )
        }

    split_implementation = _implementation("split", split_kernel)
    combine_implementation = _implementation("combine", combine_kernel)
    native_transforms = (
        (split, split_implementation),
        (combine, combine_implementation),
    )
    bound = bind_host_measurement_transforms(
        native_transforms,
        (source.id,),
    )
    source_values = measurement_value_candidates(scenario, (source,))

    executed = execute_host_measurement_transforms(
        bound, source_values, points=scenario.points
    )
    values = seal_measurement_values(
        scenario.catalog,
        executed,
        points=scenario.points,
    )

    assert calls == ["split", "combine"]
    final_values = [
        values.value_for_output(point.logical_id, result.id).value
        for point in scenario.linked_points.point_domain.points
    ]
    assert [value.value for value in final_values if isinstance(value, Quantity)] == [
        10.0,
        210.0,
    ]


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            "missing-port",
            "measurement_transform_host_output_inventory_mismatch",
        ),
        ("extra-port", "measurement_transform_host_output_inventory_mismatch"),
        ("type", "measurement_transform_host_output_carrier_invalid"),
        ("unit", "measurement_transform_host_output_unit_mismatch"),
        ("shape", "measurement_transform_host_output_shape_mismatch"),
    ),
)
def test_point_runner_rejects_wrong_kernel_outputs(
    failure: str,
    expected_code: str,
) -> None:
    def bad_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        if failure == "missing-port":
            return {}
        if failure == "extra-port":
            return {"output": call.inputs["input"], "extra": call.inputs["input"]}
        if failure == "unit":
            return {"output": (Quantity(value=1.0, unit="Hz"),) * len(call.points)}
        if failure == "shape":
            return {
                "output": (
                    MeasurementArray(
                        dtype="float64",
                        unit="ratio",
                        shape=[1],
                        values=[1.0],
                    ),
                )
                * len(call.points)
            }
        return {"output": (1,) * len(call.points)}  # pyright: ignore[reportReturnType]

    scenario, _native_transforms, bound, source = _one_transform_plan(kernel=bad_kernel)

    with pytest.raises(MeasurementTransformExecutionError) as caught:
        execute_host_measurement_transforms(bound, source, points=scenario.points)

    problem = caught.value.problems[0]
    assert problem.code == expected_code
    assert problem.phase is ProblemPhase.EXECUTION


def test_kernel_fault_is_sanitized_logged_and_safe_to_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def flaky_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret-input-payload")
        return {"output": call.inputs["input"]}

    scenario, _native_transforms, bound, source = _one_transform_plan(
        kernel=flaky_kernel
    )

    with (
        caplog.at_level("ERROR", logger="scopecat.measurements.host_transforms"),
        pytest.raises(MeasurementTransformExecutionError) as caught,
    ):
        execute_host_measurement_transforms(bound, source, points=scenario.points)

    problem = caught.value.problems[0]
    assert problem.code == "measurement_transform_host_kernel_failed"
    assert problem.phase is ProblemPhase.EXECUTION
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert problem.details["exception_type"] == "builtins.RuntimeError"
    assert "secret-input-payload" not in str(caught.value)
    assert "secret-input-payload" not in repr(problem.details)
    assert "secret-input-payload" not in caplog.text

    retried = execute_host_measurement_transforms(bound, source, points=scenario.points)
    assert len(retried) == len(source) * 2


class _ExplodingOutputMapping(Mapping[str, Sequence[MeasurementValue]]):
    @override
    def __getitem__(self, _key: str) -> Sequence[MeasurementValue]:
        raise RuntimeError("secret-mapping-payload")

    @override
    def __iter__(self):
        return iter(("output",))

    @override
    def __len__(self) -> int:
        return 1


def test_kernel_output_mapping_fault_stays_inside_transform_boundary() -> None:
    def bad_mapping_kernel(
        _call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        return _ExplodingOutputMapping()

    scenario, _native_transforms, bound, source = _one_transform_plan(
        kernel=bad_mapping_kernel
    )

    with pytest.raises(MeasurementTransformExecutionError) as caught:
        execute_host_measurement_transforms(bound, source, points=scenario.points)

    problem = caught.value.problems[0]
    assert problem.code == "measurement_transform_host_output_container_invalid"
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "secret-mapping-payload" not in str(caught.value)
    assert "secret-mapping-payload" not in repr(problem.details)


def test_point_runner_requires_exact_source_value_inventory() -> None:
    scenario, _native_transforms, bound, source = _one_transform_plan()

    with pytest.raises(MeasurementTransformExecutionError) as missing:
        execute_host_measurement_transforms(bound, (), points=scenario.points)
    with pytest.raises(MeasurementTransformExecutionError) as duplicate:
        execute_host_measurement_transforms(
            bound, (*source, *source), points=scenario.points
        )

    assert missing.value.problems[0].code == (
        "measurement_transform_source_value_missing"
    )
    assert duplicate.value.problems[0].code == (
        "measurement_transform_source_value_duplicate"
    )


def test_zero_point_runner_closes_without_calling_kernel() -> None:
    calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    scenario, _native_transforms, bound, source = _one_transform_plan(
        point_values=(), kernel=kernel
    )

    executed = execute_host_measurement_transforms(
        bound, source, points=scenario.points
    )

    assert calls == 0
    assert executed == ()


def test_record_aliases_do_not_multiply_transform_execution() -> None:
    calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    scenario, _native_transforms, bound, source = _one_transform_plan(kernel=kernel)

    execute_host_measurement_transforms(bound, source, points=scenario.points)

    # The scenario has primary+alias RecordUse edges for one product use.  The
    # transform still runs once for the whole point coverage, never once per record.
    assert len(scenario.linked_points.linked_plan.program.record_uses) == 3
    assert calls == 1


def test_point_runner_fans_one_semantic_output_out_to_every_product_use() -> None:
    scenario = measurement_assembly_scenario(use_count=3, shared_product=True)
    source, first_output, second_output = scenario.uses
    transform = MeasurementTransformDef(
        id=NativeMeasurementTransformId("fan-out"),
        semantic=_semantic("identity"),
        inputs=(_input_port(scenario, "input", source),),
        outputs=(
            MeasurementTransformOutputPort(
                id="output",
                product_use_ids=(first_output.id, second_output.id),
                product=_product(scenario, first_output),
            ),
        ),
    )
    calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    implementation = _implementation("identity", kernel)
    bound = bind_host_measurement_transforms(
        ((transform, implementation),),
        (source.id,),
    )
    source_values = measurement_value_candidates(scenario, (source,))

    executed = execute_host_measurement_transforms(
        bound, source_values, points=scenario.points
    )
    values = seal_measurement_values(
        scenario.catalog,
        executed,
        points=scenario.points,
    )

    assert calls == 1
    for point in scenario.linked_points.point_domain.points:
        first = values.value_for_output(point.logical_id, first_output.id)
        second = values.value_for_output(point.logical_id, second_output.id)
        assert first.value == second.value
