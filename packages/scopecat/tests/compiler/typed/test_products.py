from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_verified_program
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    AcquireSpec,
    CoreProgram,
    LogicalResourceRequirement,
    core_acquisitions,
)
from scopecat.compiler.typed.records import RecordAxisPlan, RecordPlan, RecordUse
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.execution.local.program import CollectOperation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from scopecat.kernel.resource_identity import LogicalResourcePortId
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


def _program(
    *,
    products: tuple[ProductDef, ...],
    acquisitions: tuple[AcquireSpec, ...] = (),
    uses: tuple[ProductUse, ...] = (),
    records: tuple[RecordUse, ...] = (),
) -> CoreProgram:
    capabilities_by_port: dict[LogicalResourcePortId, set[str]] = {}
    for acquisition in acquisitions:
        capabilities = capabilities_by_port.setdefault(
            acquisition.resource_port_id,
            set(),
        )
        capabilities.add(acquisition.capability_id)
    return CoreProgram(
        id="product-ir",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        resource_requirements=tuple(
            LogicalResourceRequirement(
                port_id=port_id,
                capabilities=tuple(sorted(capabilities)),
            )
            for port_id, capabilities in capabilities_by_port.items()
        ),
        effects=acquisitions,
        product_defs=products,
        product_uses=uses,
        record_uses=records,
    )


def _duplicate_use_program() -> CoreProgram:
    product = _product()
    use = product_use(product.id)
    return _program(products=(product,), uses=(use, use))


def test_compiler_product_and_record_metadata_is_recursively_immutable() -> None:
    metadata: dict[str, JsonValue] = {
        "labels": ["original"],
        "owner": {"name": "original"},
    }
    axis = ProductAxisDef(
        id="shot",
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
        capability="scalar_signal",
        metadata=metadata,
    )
    use = product_use(product.id)
    record_use = RecordUse(id="signal", product_use_id=use.id, metadata=metadata)
    record_axis = RecordAxisPlan(
        id="shot",
        kind="shot",
        size=2,
        metadata=metadata,
    )
    record_plan = RecordPlan(
        id="signal",
        product_use_id=use.id,
        product_id=product.id,
        kind=product.kind,
        dtype=product.dtype,
        axes=(record_axis,),
        metadata=metadata,
    )
    program = CoreProgram(
        id="immutable-metadata",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        metadata=metadata,
    )

    cast("list[JsonValue]", metadata["labels"]).append("mutated")
    cast("dict[str, JsonValue]", metadata["owner"])["name"] = "mutated"

    for selected in (
        axis.metadata,
        product.metadata,
        acquisition.products[0].metadata,
        record_use.metadata,
        record_axis.metadata,
        record_plan.metadata,
        program.metadata,
    ):
        assert selected == {
            "labels": ("original",),
            "owner": {"name": "original"},
        }
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected)["extra"] = True
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected["owner"])["name"] = "mutated"


def _duplicate_acquisition_program() -> CoreProgram:
    product = _product()
    first = instrument_acquisition(product, id="first", capability="scalar_signal")
    second = instrument_acquisition(product, id="second", capability="scalar_signal")
    return _program(
        products=(product,),
        acquisitions=(first, second),
    )


def _orphan_acquisition_program() -> CoreProgram:
    return _program(
        products=(_product("available"),),
        acquisitions=(
            instrument_acquisition(
                product_id("missing"),
                id="orphan",
                capability="scalar_signal",
            ),
        ),
    )


def test_record_aliases_share_one_product_realization() -> None:
    product = _product()
    acquisition = instrument_acquisition(
        product,
        capability="scalar_signal",
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
        link_program(program, validate_config_environment(load_config()))
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
        capability="scalar_signal",
        provider_key="raw-signal",
    )
    direct_use = ProductUse(product_id=product.id, id=ProductUseId("direct"))
    transform_use = ProductUse(product_id=product.id, id=ProductUseId("transform"))
    program = _program(
        products=(product,),
        acquisitions=(acquisition,),
        uses=(direct_use, transform_use),
        records=(RecordUse(id="direct", product_use_id=direct_use.id),),
    )

    plan = materialize_local_execution(
        link_program(program, validate_config_environment(load_config()))
    )

    [operation] = operations_of_type(plan, CollectOperation, point_index=0)
    assert [request.id for request in operation.command.requests] == ["raw-signal"]
    assert operation.result_bindings[0].product_use_ids == (
        direct_use.id,
        transform_use.id,
    )


def test_multi_product_acquisition_lowers_to_one_instrument_command() -> None:
    first = _product("first")
    second = _product("second")
    first_acquisition = instrument_acquisition(
        first,
        id="read-both",
        capability="scalar_signal",
        provider_key="first-key",
    )
    second_acquisition = instrument_acquisition(
        second,
        capability="scalar_signal",
        provider_key="second-key",
    )
    acquisition = AcquireSpec(
        id=first_acquisition.id,
        resource_port_id=first_acquisition.resource_port_id,
        capability_id="scalar_signal",
        products=(*first_acquisition.products, *second_acquisition.products),
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
            validate_config_environment(load_config()),
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
                        capability="scalar_signal",
                    ),
                    instrument_acquisition(
                        second,
                        id="after",
                        capability="scalar_signal",
                    ),
                ),
                uses=(first_use, second_use),
            ),
            validate_config_environment(load_config()),
        )
    )

    operations = operations_of_type(plan, CollectOperation, point_index=0)
    assert len({operation.operation_id for operation in operations}) == 2
    assert all(
        operation.operation_id.startswith("collect-") for operation in operations
    )


def test_record_policy_does_not_change_collection_request() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, capability="scalar_signal")
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
    environment = validate_config_environment(load_config())

    first_plan = materialize_local_execution(link_program(first, environment))
    second_plan = materialize_local_execution(link_program(second, environment))

    assert operations_of_type(
        first_plan, CollectOperation, point_index=0
    ) == operations_of_type(second_plan, CollectOperation, point_index=0)


def test_unused_product_acquisition_is_linked_without_collection() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, capability="scalar_signal")
    config = load_config()
    config = config.model_copy(
        update={"system": config.system.model_copy(update={"routing": RoutingGraph()})}
    )
    linked = link_program(
        _program(products=(product,), acquisitions=(acquisition,)),
        validate_config_environment(config),
    )

    assert linked.program.product_defs == (product,)
    assert core_acquisitions(linked.program) == (acquisition,)
    assert linked.program.product_uses == ()
    assert linked.program.record_uses == ()

    plan = materialize_local_execution(
        link_verified_program(linked.verified_program, linked.environment)
    )

    assert operations_of_type(plan, CollectOperation, point_index=0) == ()


def test_unrecorded_product_use_is_still_realized_once() -> None:
    product = _product()
    acquisition = instrument_acquisition(product, capability="scalar_signal")
    use = product_use(product.id)

    plan = materialize_local_execution(
        link_program(
            _program(
                products=(product,),
                acquisitions=(acquisition,),
                uses=(use,),
            ),
            validate_config_environment(load_config()),
        )
    )

    assert [
        product_use_id
        for operation in operations_of_type(plan, CollectOperation, point_index=0)
        for binding in operation.result_bindings
        for product_use_id in binding.product_use_ids
    ] == [use.id]


def test_demanded_product_without_an_owner_fails_before_materialization() -> None:
    product = ProductDef(id=product_id("derived"))
    use = product_use(product.id)

    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(
            link_program(
                _program(products=(product,), uses=(use,)),
                validate_config_environment(load_config()),
            )
        )

    assert [problem.code for problem in failure.value.problems] == [
        "product_acquire_missing"
    ]


@pytest.mark.parametrize(
    ("program", "expected_code"),
    (
        (
            lambda: _program(products=(_product(), _product())),
            "product_definition_duplicate",
        ),
        (
            _duplicate_use_program,
            "product_use_identity_duplicate",
        ),
        (
            _duplicate_acquisition_program,
            "product_acquire_duplicate",
        ),
        (
            _orphan_acquisition_program,
            "product_acquire_definition_missing",
        ),
        (
            lambda: _program(
                products=(_product("available"),),
                uses=(ProductUse(product_id=product_id("missing")),),
            ),
            "product_use_definition_missing",
        ),
        (
            lambda: _program(
                products=(_product(),),
                records=(
                    RecordUse(
                        id="dangling",
                        product_use_id=ProductUseId.fresh(),
                    ),
                ),
            ),
            "record_product_use_missing",
        ),
    ),
)
def test_sealing_rejects_malformed_product_graph(
    program: Callable[[], CoreProgram],
    expected_code: str,
) -> None:
    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program())

    assert expected_code in {problem.code for problem in caught.value.problems}
