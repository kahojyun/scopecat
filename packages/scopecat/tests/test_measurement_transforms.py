from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from scopecat._compiler.linked import MaterializedLinkedPointBatch
from scopecat._compiler.products import ProductDef
from scopecat._product_identity import ProductUse, ProductUseId
from scopecat.errors import CheckFailed, MeasurementTransformExecutionError
from scopecat.measurement_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformFragmentBinding,
    HostMeasurementTransformImplementation,
    HostMeasurementTransformImplementationBinding,
    MeasurementTransformDef,
    MeasurementTransformId,
    MeasurementTransformPort,
    MeasurementTransformSemanticContract,
    bind_host_measurement_transforms,
    execute_host_measurement_transforms,
    select_host_measurement_transforms,
    verify_measurement_transform_graph,
)
from scopecat.measurement_values import (
    ProductValueFragmentDef,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.models.measurement import MeasurementArray, MeasurementValue
from scopecat.models.parameter import Quantity
from scopecat.problems import ProblemCategory, ProblemPhase
from tests.test_measurement_value_assembly import (
    _candidates,
    _Scenario,
    _scenario,
)


def _product(scenario: _Scenario, use: ProductUse) -> ProductDef:
    products = {
        product.id: product
        for product in scenario.linked_points.linked_plan.product_defs
    }
    return products[use.product_id]


def _port(
    scenario: _Scenario,
    port_id: str,
    use: ProductUse,
) -> MeasurementTransformPort:
    return MeasurementTransformPort(
        id=port_id,
        product_use_id=use.id,
        product=_product(scenario, use),
    )


def _semantic(name: str) -> MeasurementTransformSemanticContract:
    return MeasurementTransformSemanticContract(
        id=name,
        version="1",
        parameters={"policy": name},
    )


def _transform(
    scenario: _Scenario,
    transform_id: str,
    inputs: tuple[tuple[str, ProductUse], ...],
    outputs: tuple[tuple[str, ProductUse], ...],
    *,
    semantic_id: str | None = None,
    rate: str = "point",
) -> MeasurementTransformDef:
    return MeasurementTransformDef(
        id=MeasurementTransformId(transform_id),
        semantic=_semantic(semantic_id or transform_id),
        rate=rate,  # type: ignore[arg-type]
        inputs=tuple(_port(scenario, name, use) for name, use in inputs),
        outputs=tuple(_port(scenario, name, use) for name, use in outputs),
    )


def _implementation(
    semantic_id: str,
    kernel,
    *,
    implementation_id: str | None = None,
    validator=lambda _transform: None,
) -> HostMeasurementTransformImplementation:
    return HostMeasurementTransformImplementation(
        id=implementation_id or f"host-{semantic_id}",
        semantic_id=semantic_id,
        semantic_version="1",
        rate="point",
        implementation_fingerprint=f"fingerprint-{implementation_id or semantic_id}",
        validate_transform=validator,
        kernel=kernel,
    )


def _identity_kernel(
    call: HostMeasurementTransformCall,
) -> Mapping[str, MeasurementValue]:
    value = call.inputs["input"]
    return {"output": value}


def _one_transform_plan(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
    kernel=_identity_kernel,
    rate: str = "point",
):
    scenario = _scenario(point_values=point_values, use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "normalize",
        (("input", source),),
        (("output", output),),
        semantic_id="identity",
        rate=rate,
    )
    graph = verify_measurement_transform_graph(scenario.linked_points, (transform,))
    implementation = _implementation("identity", kernel)
    selected = select_host_measurement_transforms(
        graph,
        (implementation,),
        (
            HostMeasurementTransformImplementationBinding(
                transform.id,
                implementation.id,
            ),
        ),
    )
    assembly = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(source.id, output.id),
        fragment_defs=(
            ProductValueFragmentDef("source", (source.id,)),
            ProductValueFragmentDef("derived", (output.id,)),
        ),
    )
    bound = bind_host_measurement_transforms(
        selected,
        assembly,
        (
            HostMeasurementTransformFragmentBinding(
                transform.id,
                "derived",
            ),
        ),
    )
    source_fragment = seal_measurement_value_fragment(
        assembly,
        "source",
        _candidates(scenario, (source,)),
    )
    return scenario, graph, selected, assembly, bound, source_fragment


def test_transform_graph_accepts_a_linked_point_batch() -> None:
    scenario = _scenario(point_values=(0.0, 1.0, 2.0), use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "batch-transform",
        (("input", source),),
        (("output", output),),
    )
    batch = MaterializedLinkedPointBatch(scenario.linked_points, (1, 2))

    graph = verify_measurement_transform_graph(batch, (transform,))

    assert graph.linked_points is batch


@given(order=st.permutations((0, 1, 2)))
def test_graph_order_and_fingerprint_are_declaration_order_independent(
    order: list[int],
) -> None:
    scenario = _scenario(use_count=4)
    source, first, second, independent = scenario.uses
    declarations = (
        _transform(
            scenario,
            "b-first",
            (("input", source),),
            (("output", first),),
        ),
        _transform(
            scenario,
            "c-second",
            (("input", first),),
            (("output", second),),
        ),
        _transform(
            scenario,
            "a-independent",
            (("input", source),),
            (("output", independent),),
        ),
    )
    canonical = verify_measurement_transform_graph(
        scenario.linked_points,
        declarations,
    )
    reordered = verify_measurement_transform_graph(
        scenario.linked_points,
        tuple(declarations[index] for index in order),
    )

    assert tuple(item.id.value for item in reordered.transforms) == (
        "a-independent",
        "b-first",
        "c-second",
    )
    assert reordered.transforms == canonical.transforms
    assert reordered.contract_fingerprint == canonical.contract_fingerprint


def test_graph_rejects_cycles_duplicate_output_owners_and_foreign_uses() -> None:
    scenario = _scenario(use_count=2)
    left, right = scenario.uses
    cycle = (
        _transform(
            scenario,
            "left",
            (("input", right),),
            (("output", left),),
        ),
        _transform(
            scenario,
            "right",
            (("input", left),),
            (("output", right),),
        ),
    )
    duplicate_owner = (
        _transform(
            scenario,
            "first",
            (("input", left),),
            (("output", right),),
        ),
        _transform(
            scenario,
            "second",
            (("input", left),),
            (("output", right),),
        ),
    )
    foreign = MeasurementTransformDef(
        id=MeasurementTransformId("foreign"),
        semantic=_semantic("foreign"),
        rate="point",
        inputs=(
            MeasurementTransformPort(
                id="input",
                product_use_id=ProductUseId("foreign-use"),
                product=_product(scenario, left),
            ),
        ),
        outputs=(_port(scenario, "output", right),),
    )

    for declarations in (cycle, duplicate_owner, (foreign,)):
        with pytest.raises(CheckFailed):
            verify_measurement_transform_graph(
                scenario.linked_points,
                declarations,
            )


def test_graph_rejects_duplicate_ports_and_wrong_product_snapshot() -> None:
    scenario = _scenario(use_count=2)
    source, output = scenario.uses
    duplicate = MeasurementTransformDef(
        id=MeasurementTransformId("duplicate-port"),
        semantic=_semantic("duplicate-port"),
        rate="point",
        inputs=(
            _port(scenario, "same", source),
            _port(scenario, "same", source),
        ),
        outputs=(_port(scenario, "output", output),),
    )
    wrong_product = MeasurementTransformDef(
        id=MeasurementTransformId("wrong-product"),
        semantic=_semantic("wrong-product"),
        rate="point",
        inputs=(
            MeasurementTransformPort(
                id="input",
                product_use_id=source.id,
                product=_product(scenario, output),
            ),
        ),
        outputs=(_port(scenario, "output", output),),
    )

    with pytest.raises(CheckFailed):
        verify_measurement_transform_graph(scenario.linked_points, (duplicate,))
    with pytest.raises(CheckFailed):
        verify_measurement_transform_graph(scenario.linked_points, (wrong_product,))


def test_input_and_output_port_names_are_independent_namespaces() -> None:
    scenario = _scenario(use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "same-port-name",
        (("value", source),),
        (("value", output),),
    )

    graph = verify_measurement_transform_graph(
        scenario.linked_points,
        (transform,),
    )

    assert graph.transforms[0].inputs[0].id == graph.transforms[0].outputs[0].id


def test_semantic_parameters_are_recursively_frozen_and_snapshot_inputs() -> None:
    parameters: dict[str, JsonValue] = {"nested": {"thresholds": [1.0, 2.0]}}
    semantic = MeasurementTransformSemanticContract(
        id="frozen",
        version="1",
        parameters=parameters,
    )
    fingerprint = semantic.contract_fingerprint
    nested_parameters = cast("dict[str, JsonValue]", parameters["nested"])
    thresholds = cast("list[JsonValue]", nested_parameters["thresholds"])
    thresholds.append(3.0)

    assert semantic.parameters["nested"] == {"thresholds": (1.0, 2.0)}
    assert semantic.contract_fingerprint == fingerprint
    nested = cast("dict[str, object]", semantic.parameters["nested"])
    with pytest.raises(TypeError, match="immutable"):
        nested["thresholds"] = ()


def test_host_selection_requires_explicit_binding_and_rejects_point_set() -> None:
    scenario = _scenario(use_count=2)
    source, output = scenario.uses
    point = _transform(
        scenario,
        "point",
        (("input", source),),
        (("output", output),),
        semantic_id="identity",
    )
    graph = verify_measurement_transform_graph(scenario.linked_points, (point,))
    first = _implementation("identity", _identity_kernel, implementation_id="one")
    second = _implementation("identity", _identity_kernel, implementation_id="two")

    with pytest.raises(CheckFailed):
        select_host_measurement_transforms(graph, (), ())
    with pytest.raises(CheckFailed):
        select_host_measurement_transforms(
            graph,
            (first, second),
            (
                HostMeasurementTransformImplementationBinding(point.id, first.id),
                HostMeasurementTransformImplementationBinding(point.id, second.id),
            ),
        )
    selected_second = select_host_measurement_transforms(
        graph,
        (first, second),
        (HostMeasurementTransformImplementationBinding(point.id, second.id),),
    )
    assert selected_second.implementations == (second,)
    with pytest.raises(CheckFailed):
        select_host_measurement_transforms(
            graph,
            (first,),
            (
                HostMeasurementTransformImplementationBinding(
                    point.id,
                    "unknown-implementation",
                ),
            ),
        )

    calls = 0

    def point_set_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    point_set = _transform(
        scenario,
        "point-set",
        (("input", source),),
        (("output", output),),
        semantic_id="identity",
        rate="point_set",
    )
    point_set_graph = verify_measurement_transform_graph(
        scenario.linked_points,
        (point_set,),
    )
    with pytest.raises(CheckFailed):
        select_host_measurement_transforms(
            point_set_graph,
            (
                HostMeasurementTransformImplementation(
                    id="point-set",
                    semantic_id="identity",
                    semantic_version="1",
                    rate="point_set",
                    implementation_fingerprint="point-set-fingerprint",
                    validate_transform=lambda _transform: None,
                    kernel=point_set_kernel,
                ),
            ),
            (
                HostMeasurementTransformImplementationBinding(
                    point_set.id,
                    "point-set",
                ),
            ),
        )
    assert calls == 0


def test_host_capability_validator_rejects_before_kernel() -> None:
    scenario = _scenario(use_count=2)
    source, output = scenario.uses
    transform = _transform(
        scenario,
        "validated",
        (("input", source),),
        (("output", output),),
    )
    graph = verify_measurement_transform_graph(scenario.linked_points, (transform,))
    kernel_calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        nonlocal kernel_calls
        kernel_calls += 1
        return {"output": call.inputs["input"]}

    implementation = _implementation(
        "validated",
        kernel,
        validator=lambda _transform: (_ for _ in ()).throw(
            ValueError("unsupported typed interface")
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        select_host_measurement_transforms(
            graph,
            (implementation,),
            (
                HostMeasurementTransformImplementationBinding(
                    transform.id,
                    implementation.id,
                ),
            ),
        )

    assert caught.value.problems[0].code == (
        "measurement_transform_host_capability_rejected"
    )
    assert kernel_calls == 0


def test_binding_requires_exact_transform_output_fragment_and_all_values() -> None:
    scenario, _graph, selected, assembly, _bound, _source = _one_transform_plan()
    transform_id = selected.graph.transforms[0].id

    with pytest.raises(CheckFailed):
        bind_host_measurement_transforms(selected, assembly, ())
    with pytest.raises(CheckFailed):
        bind_host_measurement_transforms(
            selected,
            assembly,
            (HostMeasurementTransformFragmentBinding(transform_id, "source"),),
        )

    incomplete = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(scenario.uses[1].id,),
        fragment_defs=(ProductValueFragmentDef("derived", (scenario.uses[1].id,)),),
    )
    with pytest.raises(CheckFailed):
        bind_host_measurement_transforms(
            selected,
            incomplete,
            (HostMeasurementTransformFragmentBinding(transform_id, "derived"),),
        )


def test_point_runner_executes_multi_output_dag_in_canonical_order() -> None:
    scenario = _scenario(use_count=4)
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
    graph = verify_measurement_transform_graph(
        scenario.linked_points,
        (combine, split),
    )
    calls: list[tuple[str, int]] = []

    def split_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        calls.append((call.transform_id.value, call.point_index))
        value = call.inputs["input"]
        assert isinstance(value, Quantity)
        return {
            "left": Quantity(value=value.value, unit=value.unit),
            "right": Quantity(value=value.value + 10.0, unit=value.unit),
        }

    def combine_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        calls.append((call.transform_id.value, call.point_index))
        left_value = call.inputs["left"]
        right_value = call.inputs["right"]
        assert isinstance(left_value, Quantity)
        assert isinstance(right_value, Quantity)
        return {
            "output": Quantity(
                value=left_value.value + right_value.value,
                unit="ratio",
            )
        }

    split_implementation = _implementation("split", split_kernel)
    combine_implementation = _implementation("combine", combine_kernel)
    selected = select_host_measurement_transforms(
        graph,
        (split_implementation, combine_implementation),
        (
            HostMeasurementTransformImplementationBinding(
                split.id,
                split_implementation.id,
            ),
            HostMeasurementTransformImplementationBinding(
                combine.id,
                combine_implementation.id,
            ),
        ),
    )
    assembly = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
        fragment_defs=(
            ProductValueFragmentDef("source", (source.id,)),
            ProductValueFragmentDef("split-values", (left.id, right.id)),
            ProductValueFragmentDef("combined", (result.id,)),
        ),
    )
    bound = bind_host_measurement_transforms(
        selected,
        assembly,
        (
            HostMeasurementTransformFragmentBinding(split.id, "split-values"),
            HostMeasurementTransformFragmentBinding(combine.id, "combined"),
        ),
    )
    source_fragment = seal_measurement_value_fragment(
        assembly,
        "source",
        _candidates(scenario, (source,)),
    )

    executed = execute_host_measurement_transforms(bound, (source_fragment,))

    assert calls == [("split", 0), ("split", 1), ("combine", 0), ("combine", 1)]
    assert tuple(fragment.fragment_id for fragment in executed.transform_fragments) == (
        "split-values",
        "combined",
    )
    final_values = [
        executed.values.value_for_output(point.logical_id, result.id).value
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
    ) -> Mapping[str, MeasurementValue]:
        if failure == "missing-port":
            return {}
        if failure == "extra-port":
            return {"output": call.inputs["input"], "extra": call.inputs["input"]}
        if failure == "unit":
            return {"output": Quantity(value=1.0, unit="Hz")}
        if failure == "shape":
            return {
                "output": MeasurementArray(
                    dtype="float64",
                    unit="ratio",
                    shape=[1],
                    values=[1.0],
                )
            }
        return {"output": 1}  # type: ignore[dict-item]

    *_prefix, bound, source = _one_transform_plan(kernel=bad_kernel)

    with pytest.raises(MeasurementTransformExecutionError) as caught:
        execute_host_measurement_transforms(bound, (source,))

    problem = caught.value.problems[0]
    assert problem.code == expected_code
    assert problem.category is ProblemCategory.OPERATION
    assert problem.phase is ProblemPhase.EXECUTION


def test_kernel_fault_is_sanitized_logged_and_safe_to_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def flaky_kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret-input-payload")
        return {"output": call.inputs["input"]}

    *_prefix, bound, source = _one_transform_plan(kernel=flaky_kernel)

    with (
        caplog.at_level("ERROR", logger="scopecat.measurement_transforms"),
        pytest.raises(MeasurementTransformExecutionError) as caught,
    ):
        execute_host_measurement_transforms(bound, (source,))

    problem = caught.value.problems[0]
    assert problem.code == "measurement_transform_host_kernel_failed"
    assert problem.category is ProblemCategory.EXTERNAL_FAILURE
    assert problem.phase is ProblemPhase.EXECUTION
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert problem.details["exception_type"] == "builtins.RuntimeError"
    assert "secret-input-payload" not in str(caught.value)
    assert "secret-input-payload" not in repr(problem.details)
    assert "secret-input-payload" not in caplog.text

    retried = execute_host_measurement_transforms(bound, (source,))
    assert len(retried.transform_fragments) == 1


class _ExplodingOutputMapping(Mapping[str, MeasurementValue]):
    def __getitem__(self, _key: str) -> MeasurementValue:
        raise RuntimeError("secret-mapping-payload")

    def __iter__(self):
        return iter(("output",))

    def __len__(self) -> int:
        return 1


def test_kernel_output_mapping_fault_stays_inside_transform_boundary() -> None:
    def bad_mapping_kernel(
        _call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        return _ExplodingOutputMapping()

    *_prefix, bound, source = _one_transform_plan(kernel=bad_mapping_kernel)

    with pytest.raises(MeasurementTransformExecutionError) as caught:
        execute_host_measurement_transforms(bound, (source,))

    problem = caught.value.problems[0]
    assert problem.code == "measurement_transform_host_output_container_invalid"
    assert problem.category is ProblemCategory.OPERATION
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "secret-mapping-payload" not in str(caught.value)
    assert "secret-mapping-payload" not in repr(problem.details)


def test_point_runner_requires_exact_source_fragment_inventory() -> None:
    *_prefix, bound, source = _one_transform_plan()

    with pytest.raises(MeasurementTransformExecutionError) as missing:
        execute_host_measurement_transforms(bound, ())
    with pytest.raises(MeasurementTransformExecutionError) as duplicate:
        execute_host_measurement_transforms(bound, (source, source))

    assert missing.value.problems[0].code == (
        "measurement_transform_source_fragment_missing"
    )
    assert missing.value.problems[0].category is ProblemCategory.INVALID_INPUT
    assert duplicate.value.problems[0].code == (
        "measurement_transform_source_fragment_duplicate"
    )
    assert duplicate.value.problems[0].category is ProblemCategory.CONFLICT


def test_zero_point_runner_closes_without_calling_kernel() -> None:
    calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    *_prefix, bound, source = _one_transform_plan(point_values=(), kernel=kernel)

    executed = execute_host_measurement_transforms(bound, (source,))

    assert calls == 0
    assert executed.values.values == ()
    assert len(executed.transform_fragments) == 1


def test_record_aliases_do_not_multiply_transform_execution() -> None:
    calls = 0

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        nonlocal calls
        calls += 1
        return {"output": call.inputs["input"]}

    scenario, *_middle, bound, source = _one_transform_plan(kernel=kernel)

    execute_host_measurement_transforms(bound, (source,))

    # The scenario has primary+alias RecordUse edges for one product use.  The
    # transform still runs exactly once per logical point, never once per record.
    assert len(scenario.linked_points.linked_plan.record_uses) == 3
    assert calls == len(scenario.linked_points.point_domain.points)


def test_public_dataclasses_reject_wrong_runtime_field_types_early() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        MeasurementTransformId(cast("str", 1))
    with pytest.raises(TypeError, match="validator must be callable"):
        HostMeasurementTransformImplementation(
            id="bad-validator",
            semantic_id="identity",
            semantic_version="1",
            rate="point",
            implementation_fingerprint="bad-validator-fingerprint",
            validate_transform=cast("object", None),  # type: ignore[arg-type]
            kernel=_identity_kernel,
        )
