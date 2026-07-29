from __future__ import annotations

from typing import cast

import pytest

from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    core_acquisitions,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import CollectOperation
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.measurements.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.measurements.records import (
    RecordAxisPlan,
    RecordPlan,
    RecordUse,
    validate_record_plan,
)
from scopecat.measurements.results import MeasurementDType
from scopecat.records.config import RoutingGraph
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.typed_program import instrument_acquisition, link_program


def _product(name: str = "signal") -> ProductDef:
    return ProductDef(
        id=product_id(name),
        unit="ratio",
        metadata={"definition": name},
    )


@pytest.mark.parametrize("dtype", ["bool", "string"])
def test_bool_and_string_products_reject_units(
    dtype: MeasurementDType,
) -> None:
    with pytest.raises(ValueError, match="cannot have a unit"):
        ProductDef(
            id=product_id("invalid"),
            dtype=dtype,
            unit="ratio",
        )


def test_product_axes_require_distinct_non_point_dimensions() -> None:
    first = ProductAxisDef(
        id="i",
        dimension_id="shared/sample",
        kind="sample",
        size=2,
    )
    second = ProductAxisDef(
        id="q",
        dimension_id="shared/sample",
        kind="sample",
        size=2,
    )

    with pytest.raises(ValueError, match="distinct dataset dimensions"):
        ProductDef(
            id=product_id("invalid"),
            axes=(first, second),
        )
    with pytest.raises(ValueError, match="dimension id point is reserved"):
        ProductAxisDef(
            id="sample",
            dimension_id="point",
            kind="sample",
            size=2,
        )


def test_product_axes_require_distinct_acquisition_local_ids() -> None:
    with pytest.raises(ValueError, match="distinct acquisition-local ids"):
        ProductDef(
            id=product_id("invalid"),
            axes=(
                ProductAxisDef(
                    id="sample",
                    dimension_id="product/invalid/first",
                    kind="sample",
                    size=2,
                ),
                ProductAxisDef(
                    id="sample",
                    dimension_id="product/invalid/second",
                    kind="sample",
                    size=2,
                ),
            ),
        )


def _program(
    *,
    products: tuple[ProductDef, ...],
    acquisitions: tuple[AcquireEffect, ...] = (),
    uses: tuple[ProductUse, ...] = (),
    records: tuple[RecordUse, ...] = (),
) -> CoreProgram:
    interfaces_by_port: dict[LogicalResourcePortId, set[str]] = {}
    for acquisition in acquisitions:
        interfaces = interfaces_by_port.setdefault(
            acquisition.resource_port_id,
            set(),
        )
        interfaces.add(acquisition.interface_id)
    return CoreProgram(
        id="product-ir",
        kind="compiler_test",
        point_domain=PointDomain(axes=()),
        resource_requirements=tuple(
            LogicalResourceRequirement(
                port_id=port_id,
                interfaces=tuple(sorted(interfaces)),
            )
            for port_id, interfaces in interfaces_by_port.items()
        ),
        effects=acquisitions,
        product_defs=products,
        product_uses=uses,
        record_uses=records,
    )


def test_compiler_product_and_record_metadata_is_recursively_immutable() -> None:
    metadata: dict[str, JsonValue] = {
        "labels": ["original"],
        "owner": {"name": "original"},
    }
    axis = ProductAxisDef(
        id="shot",
        dimension_id="product/signal/shot",
        dimension_label="shot",
        kind="shot",
        size=2,
        metadata=metadata,
    )
    product = ProductDef(
        id=product_id("signal"),
        axes=(axis,),
        metadata=metadata,
    )
    acquisition = instrument_acquisition(
        product,
        interface="test.scalar_signal/v1",
        metadata=metadata,
    )
    use = product_use(product.id)
    record_use = RecordUse(id="signal", product_use_id=use.id, metadata=metadata)
    record_axis = RecordAxisPlan(
        id="product/signal/shot",
        label="shot",
        kind="shot",
        size=2,
        metadata=metadata,
    )
    record_plan = RecordPlan(
        id="signal",
        product_use_id=use.id,
        product_id=product.id,
        dtype=product.dtype,
        axes=(record_axis,),
        metadata=metadata,
    )
    cast("list[JsonValue]", metadata["labels"]).append("mutated")
    cast("dict[str, JsonValue]", metadata["owner"])["name"] = "mutated"

    for selected in (
        axis.metadata,
        product.metadata,
        acquisition.results[0].metadata,
        record_use.metadata,
        record_axis.metadata,
        record_plan.metadata,
    ):
        assert selected == {
            "labels": ("original",),
            "owner": {"name": "original"},
        }
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected)["extra"] = True
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected["owner"])["name"] = "mutated"


def test_record_plan_boundary_rejects_duplicate_and_coordinate_ids() -> None:
    product = _product()
    use = product_use(product.id)
    record = RecordPlan(
        id="signal",
        product_use_id=use.id,
        product_id=product.id,
        dtype=product.dtype,
    )

    problems = validate_record_plan(
        (record, record),
        coordinate_ids=("signal",),
    )

    assert [problem.code for problem in problems] == [
        "experiment_record_duplicate",
        "experiment_record_coordinate_collision",
    ]


def test_record_plan_rejects_variable_and_inner_dimension_collision() -> None:
    product = _product()
    use = product_use(product.id)
    record = RecordPlan(
        id="signal",
        product_use_id=use.id,
        product_id=product.id,
        dtype=product.dtype,
        axes=(
            RecordAxisPlan(
                id="signal",
                label="sample",
                kind="sample",
                size=2,
            ),
        ),
    )

    problems = validate_record_plan((record,))

    assert [problem.code for problem in problems] == [
        "experiment_record_dimension_collision"
    ]


def test_record_aliases_share_one_product_realization() -> None:
    product = _product()
    acquisition = instrument_acquisition(
        product,
        interface="test.scalar_signal/v1",
        metadata={"producer": "signal"},
    )
    use = product_use(product.id)
    program = _program(
        products=(product,),
        acquisitions=(acquisition,),
        uses=(use,),
        records=(
            RecordUse(
                id="primary",
                product_use_id=use.id,
                metadata={"record": "primary"},
            ),
            RecordUse(
                id="secondary",
                product_use_id=use.id,
                metadata={"record": "secondary"},
            ),
        ),
    )

    plan = materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )

    operation = operations_of_type(plan, CollectOperation, point_index=0)[0]
    requests = operation.command.requests
    assert len(requests) == 1
    assert operation.result_bindings[0].product_use_ids == (use.id,)
    assert requests[0].metadata == {"producer": "signal"}


def test_one_provider_result_fans_out_to_every_use_of_the_product() -> None:
    product = _product()
    acquisition = instrument_acquisition(
        product,
        interface="test.scalar_signal/v1",
        result_id="raw-signal",
    )
    direct_use = ProductUse(product_id=product.id, id=ProductUseId("direct"))
    postprocessor_use = ProductUse(
        product_id=product.id,
        id=ProductUseId("postprocessor"),
    )
    program = _program(
        products=(product,),
        acquisitions=(acquisition,),
        uses=(direct_use, postprocessor_use),
        records=(RecordUse(id="direct", product_use_id=direct_use.id),),
    )

    plan = materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )

    [operation] = operations_of_type(plan, CollectOperation, point_index=0)
    assert [request.id for request in operation.command.requests] == ["raw-signal"]
    assert operation.result_bindings[0].product_use_ids == (
        direct_use.id,
        postprocessor_use.id,
    )


def test_multi_product_acquisition_lowers_to_one_instrument_command() -> None:
    first = _product("first")
    second = _product("second")
    first_acquisition = instrument_acquisition(
        first,
        id="read-both",
        interface="test.scalar_signal/v1",
        result_id="first-key",
    )
    second_acquisition = instrument_acquisition(
        second,
        interface="test.scalar_signal/v1",
        result_id="second-key",
    )
    acquisition = AcquireEffect(
        id=first_acquisition.id,
        resource_port_id=first_acquisition.resource_port_id,
        interface_id="test.scalar_signal/v1",
        component_path=(),
        acquisition_id="sample",
        results=(*first_acquisition.results, *second_acquisition.results),
    )
    first_use = product_use(first.id)
    second_use = product_use(second.id)

    plan = materialize_local_execution(
        link_program(
            _program(
                products=(first, second),
                acquisitions=(acquisition,),
                uses=(first_use, second_use),
            ),
            build_config_environment(load_config()),
        )
    )

    [operation] = operations_of_type(plan, CollectOperation, point_index=0)
    assert [request.id for request in operation.command.requests] == [
        "first-key",
        "second-key",
    ]
    assert [binding.product_use_ids for binding in operation.result_bindings] == [
        (first_use.id,),
        (second_use.id,),
    ]


def test_ordered_acquisitions_on_one_instrument_have_distinct_operation_ids() -> None:
    first = _product("first")
    second = _product("second")
    first_use = product_use(first.id)
    second_use = product_use(second.id)

    plan = materialize_local_execution(
        link_program(
            _program(
                products=(first, second),
                acquisitions=(
                    instrument_acquisition(
                        first,
                        id="before",
                        interface="test.scalar_signal/v1",
                    ),
                    instrument_acquisition(
                        second,
                        id="after",
                        interface="test.scalar_signal/v1",
                    ),
                ),
                uses=(first_use, second_use),
            ),
            build_config_environment(load_config()),
        )
    )

    operations = operations_of_type(plan, CollectOperation, point_index=0)
    assert len({operation.operation_id for operation in operations}) == 2
    assert all(
        operation.operation_id.startswith("collect-") for operation in operations
    )


def test_record_policy_does_not_change_collection_request() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, interface="test.scalar_signal/v1")
    use = product_use(product.id)
    first = _program(
        products=(product,),
        acquisitions=(acquisition,),
        uses=(use,),
        records=(RecordUse(id="first", product_use_id=use.id),),
    )
    second = _program(
        products=(product,),
        acquisitions=(acquisition,),
        uses=(use,),
        records=(
            RecordUse(
                id="renamed",
                product_use_id=use.id,
                metadata={"policy": "changed"},
            ),
        ),
    )
    environment = build_config_environment(load_config())

    first_plan = materialize_local_execution(link_program(first, environment))
    second_plan = materialize_local_execution(link_program(second, environment))

    assert operations_of_type(
        first_plan, CollectOperation, point_index=0
    ) == operations_of_type(second_plan, CollectOperation, point_index=0)


def test_unused_product_acquisition_is_linked_without_collection() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, interface="test.scalar_signal/v1")
    config = load_config()
    config = config.model_copy(
        update={"system": config.system.model_copy(update={"routing": RoutingGraph()})}
    )
    linked = link_program(
        _program(products=(product,), acquisitions=(acquisition,)),
        build_config_environment(config),
    )

    assert linked.program.product_defs == (product,)
    assert core_acquisitions(linked.program) == (acquisition,)
    assert linked.program.product_uses == ()
    assert linked.program.record_uses == ()

    plan = materialize_local_execution(linked)

    assert operations_of_type(plan, CollectOperation, point_index=0) == ()


def test_unrecorded_product_use_is_still_realized_once() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, interface="test.scalar_signal/v1")
    use = product_use(product.id)

    plan = materialize_local_execution(
        link_program(
            _program(
                products=(product,),
                acquisitions=(acquisition,),
                uses=(use,),
            ),
            build_config_environment(load_config()),
        )
    )

    assert [
        product_use_id
        for operation in operations_of_type(plan, CollectOperation, point_index=0)
        for binding in operation.result_bindings
        for product_use_id in binding.product_use_ids
    ] == [use.id]
