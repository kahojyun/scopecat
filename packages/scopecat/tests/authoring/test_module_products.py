# pyright: reportUnusedFunction=false

from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.instrument_members import AcquisitionResultRef
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.program.products import (
    ModuleProductDecl,
    RecordSelection,
    product_axis,
    product_axis_dimension_id,
)
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import bind_invocation, load_config

_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SAMPLE = _SCALAR_SIGNAL.acquisition("sample")


def _product_module() -> sc.ExperimentModule[...]:
    @sc.module(id="test.products.source")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        signal = context.product(
            "signal",
            unit="ratio",
        )
        context.acquire(
            "read-signal",
            resource=source,
            results={_SAMPLE.result("signal"): signal},
            metadata={"adapter_mode": "default"},
        )

    return module


def test_selected_product_lowers_schema_and_acquisition_metadata_independently(
    tmp_path: Path,
) -> None:
    @sc.module(id="test.products.metadata")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        signal = context.product(
            "signal",
            metadata={"schema_owner": "analysis"},
        )
        context.acquire(
            "read-signal",
            resource=source,
            results={_SAMPLE.result("signal"): signal},
            metadata={"adapter_mode": "fast"},
        )

    call = module()

    @sc.template(id="test.products.metadata", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(call.products.signal)

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    assert resolved.bindings.product_defs[0].metadata == {"schema_owner": "analysis"}
    assert resolved.program.program.acquisitions[0].results[0].metadata == {
        "adapter_mode": "fast"
    }
    assert [record.id for record in resolved.bindings.record_uses] == ["signal"]


def test_product_axes_use_product_local_dimensions_by_default() -> None:
    @sc.module(id="test.products.local-axis")
    def module(context: sc.ModuleContext) -> None:
        context.product(
            "i",
            axes=(sc.product_axis("sample", size=2),),
        )
        context.product(
            "q",
            axes=(
                sc.product_axis(
                    "sample",
                    size=3,
                    kind="independent_sample",
                ),
            ),
        )

    call = module()

    @sc.template(id="test.products.local-axis", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    dimensions = [
        product.axes[0].dimension_id for product in resolved.bindings.product_defs
    ]
    assert len(set(dimensions)) == 2
    assert all(dimension.startswith("product/") for dimension in dimensions)


def test_product_axes_share_dimensions_only_when_explicit() -> None:
    @sc.module(id="test.products.shared-axis")
    def module(context: sc.ModuleContext) -> None:
        context.product(
            "i",
            axes=(
                sc.product_axis(
                    "i_sample",
                    size=2,
                    kind="sample",
                    shared_as="sample",
                ),
            ),
        )
        context.product(
            "q",
            axes=(
                sc.product_axis(
                    "q_sample",
                    size=2,
                    kind="sample",
                    shared_as="sample",
                ),
            ),
        )

    call = module()

    @sc.template(id="test.products.shared-axis", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    dimensions = [
        product.axes[0].dimension_id for product in resolved.bindings.product_defs
    ]
    assert len(set(dimensions)) == 1
    assert dimensions[0].startswith("shared/")


def test_local_and_shared_axis_namespaces_cannot_collide() -> None:
    local_product = ModuleProductDecl(id="capture", scope=("nested",))
    shared_product = ModuleProductDecl(
        id="derived",
        scope=("nested", "capture"),
    )
    local_axis = product_axis("sample", size=2)
    shared_axis = product_axis("other", size=2, shared_as="sample")

    assert product_axis_dimension_id(
        local_product,
        local_axis,
    ) != product_axis_dimension_id(shared_product, shared_axis)


def test_conflicting_explicitly_shared_product_axes_are_rejected() -> None:
    @sc.module(id="test.products.shared-axis-conflict")
    def module(context: sc.ModuleContext) -> None:
        context.product(
            "i",
            axes=(
                sc.product_axis(
                    "sample",
                    size=2,
                    shared_as="sample",
                ),
            ),
        )
        context.product(
            "q",
            axes=(
                sc.product_axis(
                    "sample",
                    size=3,
                    shared_as="sample",
                ),
            ),
        )

    call = module()

    @sc.template(id="test.products.shared-axis-conflict", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template_definition())

    assert [problem.code for problem in error.value.problems] == [
        "product_axis_conflict"
    ]


def test_acquire_is_an_ordered_effect() -> None:
    @sc.module(id="test.products.acquire")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        signal = context.product("signal")
        context.acquire(
            "read-signal",
            resource=source,
            results={_SAMPLE.result("signal"): signal},
        )

    assembly = compose_module(module.definition)

    acquire = assembly.acquisitions[0]
    assert assembly.effects == (acquire,)
    assert acquire.product_ids == (module.products.signal.product_id,)


def test_component_scoped_members_lower_complete_targets() -> None:
    interface = InterfaceRef("test.component_signal/v1")
    channel = interface.component("rack").component("channel")

    @sc.module(id="test.products.component-targets")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(interface,))
        context.bind_property(source, channel.property("gain"), value=1.0)
        context.invoke(
            "zero-channel",
            resource=source,
            operation=channel.operation("zero"),
        )
        signal = context.product("signal")
        context.acquire(
            "read-signal",
            resource=source,
            results={channel.acquisition("sample").result("signal"): signal},
        )

    assembly = compose_module(module.definition)
    [binding] = assembly.bindings
    [invocation] = assembly.invocations
    [acquisition] = assembly.acquisitions

    assert binding.interface_id == interface.interface_id
    assert binding.component_path == ("rack", "channel")
    assert binding.property_id == "gain"
    assert invocation.interface_id == interface.interface_id
    assert invocation.component_path == ("rack", "channel")
    assert invocation.operation_id == "zero"
    assert acquisition.interface_id == interface.interface_id
    assert acquisition.component_path == ("rack", "channel")
    assert acquisition.acquisition_id == "sample"
    assert acquisition.results[0].result_id == "signal"


def test_multi_product_result_mapping_lowers_from_public_authoring_api(
    tmp_path: Path,
) -> None:
    @sc.module(id="test.products.result-mapping")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        first = context.product("first")
        second = context.product("second")
        default = context.product("default")
        context.acquire(
            "read-all",
            resource=source,
            results={
                _SAMPLE.result("raw-first"): first,
                _SAMPLE.result("raw-second"): second,
                _SAMPLE.result("default"): default,
            },
        )

    call = module()

    @sc.template(id="test.products.result-mapping", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(
            call.products.first,
            call.products.second,
            call.products.default,
        )

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    [acquisition] = resolved.program.program.acquisitions
    assert acquisition.interface_id == "test.scalar_signal/v1"
    assert [
        (result.product_id.local_id, result.result_id) for result in acquisition.results
    ] == [
        ("first", "raw-first"),
        ("second", "raw-second"),
        ("default", "default"),
    ]


def test_acquire_rejects_invalid_result_mappings() -> None:
    with pytest.raises(ValueError, match="non-empty id and result mapping"):

        @sc.module(id="test.products.invalid-result-mapping.empty")
        def empty_results(context: sc.ModuleContext) -> None:
            source = context.resource("source", requires=(_SCALAR_SIGNAL,))
            context.acquire("read-both", resource=source, results={})

    mismatched_results = (
        _SCALAR_SIGNAL.acquisition("other").result("raw-second"),
        _SCALAR_SIGNAL.component("channel").acquisition("sample").result("raw-second"),
        InterfaceRef("test.other_signal/v1").acquisition("sample").result("raw-second"),
    )

    def define_mismatched_acquisition(
        mismatched_result: AcquisitionResultRef,
    ) -> None:
        @sc.module(id="test.products.invalid-result-mapping.acquisition")
        def mismatched_acquisition(context: sc.ModuleContext) -> None:
            source = context.resource("source", requires=(_SCALAR_SIGNAL,))
            first = context.product("first")
            second = context.product("second")
            context.acquire(
                "read-both",
                resource=source,
                results={
                    _SAMPLE.result("raw-first"): first,
                    mismatched_result: second,
                },
            )

    for mismatched_result in mismatched_results:
        with pytest.raises(ValueError, match="one acquisition"):
            define_mismatched_acquisition(mismatched_result)

    with pytest.raises(ValueError, match="unique products"):

        @sc.module(id="test.products.invalid-result-mapping.duplicate")
        def duplicate_product(context: sc.ModuleContext) -> None:
            source = context.resource("source", requires=(_SCALAR_SIGNAL,))
            first = context.product("first")
            context.acquire(
                "read-both",
                resource=source,
                results={
                    _SAMPLE.result("raw-first"): first,
                    _SAMPLE.result("raw-second"): first,
                },
            )

    @sc.module(id="test.products.foreign")
    def foreign(context: sc.ModuleContext) -> None:
        context.product("first")

    with pytest.raises(ValueError, match="outside this module"):

        @sc.module(id="test.products.invalid-result-mapping.foreign")
        def foreign_product(context: sc.ModuleContext) -> None:
            source = context.resource("source", requires=(_SCALAR_SIGNAL,))
            context.acquire(
                "read-foreign",
                resource=source,
                results={_SAMPLE.result("raw-first"): foreign.products.first},
            )


def test_explicit_instances_select_same_named_products_independently(
    tmp_path: Path,
) -> None:
    source = _product_module()
    left = source.instantiate("left")
    right = source.instantiate("right")

    @sc.module(id="test.products.root")
    def root(context: sc.ModuleContext) -> None:
        context.call(left)
        context.call(right)

    assert isinstance(left.products, sc.ProductOutputs)
    assert isinstance(left.products.signal, sc.ProductRef)
    assert left.products.signal.id == "left/signal"
    assert right.products["signal"].id == "right/signal"

    assembly = compose_module(root.definition)
    assert [product.qualified_id for product in assembly.product_declarations] == [
        "left/signal",
        "right/signal",
    ]
    assert [port.qualified_id for port in assembly.resource_ports] == [
        "left/source",
        "right/source",
    ]
    call = root()

    @sc.template(id="test.products.root", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(
            call.products["left/signal"],
            record_id="left_signal",
        )
        experiment.record(
            call.products["right/signal"],
            record_id="right_signal",
        )

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    assert [record.id for record in resolved.bindings.record_uses] == [
        "left_signal",
        "right_signal",
    ]
    uses_by_id = {use.id: use for use in resolved.bindings.product_uses}
    products_by_id = {product.id: product for product in resolved.bindings.product_defs}
    selected_products = [
        products_by_id[uses_by_id[record.product_use_id].product_id]
        for record in resolved.bindings.record_uses
    ]
    acquisitions_by_product = {
        result.product_id: (acquisition, result)
        for acquisition in resolved.program.program.acquisitions
        for result in acquisition.results
    }
    selected_acquisitions = [
        acquisitions_by_product[product.id] for product in selected_products
    ]
    assert [product.id.qualified_name for product in selected_products] == [
        "root/left/signal",
        "root/right/signal",
    ]
    assert [product.product_id for _acquisition, product in selected_acquisitions] == [
        product.id for product in selected_products
    ]
    assert [product.result_id for _acquisition, product in selected_acquisitions] == [
        "signal",
        "signal",
    ]
    assert [
        acquisition.resource_port_id for acquisition, _product in selected_acquisitions
    ] == [
        logical_resource_port_id(SymbolId(scope=("root", "left"), local_id="source")),
        logical_resource_port_id(SymbolId(scope=("root", "right"), local_id="source")),
    ]
    assert [
        acquisition.interface_id for acquisition, _product in selected_acquisitions
    ] == ["test.scalar_signal/v1", "test.scalar_signal/v1"]
    assert [product.metadata for _acquisition, product in selected_acquisitions] == [
        {"adapter_mode": "default"},
        {"adapter_mode": "default"},
    ]


def test_nested_product_references_receive_each_parent_instance_prefix(
    tmp_path: Path,
) -> None:
    inner = _product_module().instantiate("inner")

    @sc.module(id="test.products.wrapper")
    def wrapper(context: sc.ModuleContext) -> None:
        context.call(inner)

    projected = wrapper.definition.products[0]
    expected_projection = ProductId(SymbolId(scope=("inner",), local_id="signal"))
    assert projected.symbol_id == expected_projection
    assert projected.target_id == expected_projection
    outer = wrapper.instantiate("outer")

    @sc.module(id="test.products.nested-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(outer)

    assert set(outer.products) == {"inner/signal"}
    nested_product = outer.products["inner/signal"]
    assert nested_product.id == "outer/inner/signal"
    assembly = compose_module(root.definition)
    assert [product.qualified_id for product in assembly.product_declarations] == [
        "outer/inner/signal"
    ]
    call = root()
    nested_product = call.products["outer/inner/signal"]

    @sc.template(id="test.products.nested", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(
            nested_product,
            record_id="nested_signal",
        )

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    record = resolved.bindings.record_uses[0]
    use = next(
        use for use in resolved.bindings.product_uses if use.id == record.product_use_id
    )
    assert record.id == "nested_signal"
    expected_product_id = ProductId(
        SymbolId(scope=("nested-root", "outer", "inner"), local_id="signal")
    )
    assert use.product_id == expected_product_id
    [acquisition] = resolved.program.program.acquisitions
    [acquired_result] = acquisition.results
    assert acquired_result.product_id == expected_product_id
    assert acquisition.resource_port_id == logical_resource_port_id(
        SymbolId(
            scope=("nested-root", "outer", "inner"),
            local_id="source",
        )
    )
    assert acquired_result.result_id == "signal"
    assert acquisition.interface_id == "test.scalar_signal/v1"


def test_product_selection_rejects_unexposed_product() -> None:
    source = _product_module()
    selected = source.instantiate("selected")

    @sc.module(id="test.products.selection-validation")
    def root(context: sc.ModuleContext) -> None:
        context.call(selected)

    call = root()

    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record("signal")
        experiment.record(
            call.products["selected/signal"],
            record_id="first",
        )
        experiment.record(
            call.products["selected/signal"],
            record_id="second",
        )

    template = sc.template(
        id="test.products.selection-validation",
        kind="module_products",
    )(template_definition)

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template())

    assert [problem.code for problem in error.value.problems] == [
        "module_product_unknown",
    ]


def test_repeated_product_selection_creates_distinct_use_occurrences(
    tmp_path: Path,
) -> None:
    source = _product_module()
    selected = source.instantiate("selected")

    @sc.module(id="test.products.repeated-use")
    def root(context: sc.ModuleContext) -> None:
        context.call(selected)

    call = root()

    @sc.template(id="test.products.repeated-use", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(
            call.products["selected/signal"],
            record_id="first",
        )
        experiment.record(
            call.products["selected/signal"],
            record_id="second",
        )

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    assert len(resolved.bindings.product_uses) == 2
    assert len({use.id for use in resolved.bindings.product_uses}) == 2
    assert {use.product_id for use in resolved.bindings.product_uses} == {
        ProductId(SymbolId(scope=("repeated-use", "selected"), local_id="signal"))
    }


def test_record_coordinate_aliases_share_one_public_product_use(tmp_path: Path) -> None:
    source = _product_module()
    selected = source.instantiate("selected")

    @sc.module(id="test.products.alias")
    def root(context: sc.ModuleContext) -> None:
        context.call(selected)

    call = root()
    primary = sc.record_coordinate(
        call.products["selected/signal"],
        record_id="primary",
    )
    secondary = sc.record_alias(
        primary,
        record_id="secondary",
        metadata={"projection": "secondary"},
    )

    @sc.template(id="test.products.alias", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.records(primary, secondary)

    resolved = bind_invocation(
        template_definition(),
        config_profile=load_config(),
    )

    assert len(resolved.bindings.product_uses) == 1
    assert [record.id for record in resolved.bindings.record_uses] == [
        "primary",
        "secondary",
    ]
    assert {record.product_use_id for record in resolved.bindings.record_uses} == {
        resolved.bindings.product_uses[0].id
    }
    assert [record.role for record in resolved.bindings.record_uses] == [
        "coordinate",
        "coordinate",
    ]
    assert resolved.bindings.record_uses[1].metadata == {"projection": "secondary"}


def test_authoring_compile_rejects_one_use_identity_for_two_products() -> None:
    @sc.module(id="test.products.conflicting-use")
    def module(context: sc.ModuleContext) -> None:
        context.product("signal")
        context.product("phase")

    shared_id = ProductUseId("shared-use")
    call = module()

    @sc.template(id="test.products.conflicting-use", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        selections = (
            RecordSelection(
                product_use=ProductUse(
                    product_id=call.products.signal.product_id,
                    id=shared_id,
                ),
                record_id="signal",
            ),
            RecordSelection(
                product_use=ProductUse(
                    product_id=call.products.phase.product_id,
                    id=shared_id,
                ),
                record_id="phase",
            ),
        )
        experiment.run(call)
        experiment.records(*selections)

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template_definition())

    assert [problem.code for problem in error.value.problems] == [
        "product_use_identity_conflict"
    ]
    assert error.value.problems[0].phase is ProblemPhase.AUTHORING


def test_root_module_products_are_typed_template_refs() -> None:
    source = _product_module()
    call = source()

    @sc.template(id="test.products.root-ref", kind="module_products")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)
        experiment.record(call.products.signal)

    selection = template_definition.definition.record_selections[0]
    assert selection.product_id == ProductId(
        SymbolId(scope=("source",), local_id="signal")
    )
    assert selection.product_use.product_id == selection.product_id


def test_product_refs_are_nominally_owned_by_the_selected_instance() -> None:
    left_definition = _product_module()
    right_definition = _product_module()
    foreign = left_definition.instantiate("same")
    selected = right_definition.instantiate("same")

    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(selected)
        experiment.record(foreign.products.signal)

    template = sc.template(id="test.products.nominal", kind="module_products")(
        template_definition
    )

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template())

    assert [problem.code for problem in error.value.problems] == [
        "module_product_foreign_instance"
    ]
