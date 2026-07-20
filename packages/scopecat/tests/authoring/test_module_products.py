from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring._products import RecordSelection
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.compiler.typed.program import core_acquisitions
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.planning.authoring import resolve_experiment
from tests.testkit.authoring import load_config


def _product_module() -> sc.ExperimentModule:
    return (
        sc.module("test.products.source")
        .resource("source", requires=("scalar_signal",))
        .product(
            "signal",
            unit="ratio",
        )
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
            metadata={"adapter_mode": "default"},
        )
        .build()
    )


def test_selected_product_lowers_schema_and_acquisition_metadata_independently(
    tmp_path: Path,
) -> None:
    module = (
        sc.module("test.products.metadata")
        .resource("source", requires=("scalar_signal",))
        .product(
            "signal",
            metadata={"schema_owner": "analysis"},
        )
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
            metadata={"adapter_mode": "fast"},
        )
        .build()
    )
    resolved = resolve_experiment(
        module.template(
            "test.products.metadata",
            kind="module_products",
        )
        .record_product("signal")
        .build()
        .bind(),
        config_profile=load_config(),
    )

    assert resolved.experiment.product_defs[0].metadata == {"schema_owner": "analysis"}
    assert core_acquisitions(resolved.experiment)[0].products[0].metadata == {
        "adapter_mode": "fast"
    }


def test_acquire_is_an_ordered_effect_with_source_provenance() -> None:
    builder = (
        sc.module("test.products.acquire")
        .resource("source", requires=("scalar_signal",))
        .product("signal")
    )
    module = builder.acquire(
        "read-signal",
        builder.products.signal,
        resource="source",
        capability="scalar_signal",
    ).build()
    assembly = elaborate_module(module)

    acquire = assembly.semantic_graph.acquisitions[0]
    assert acquire.product_ids == (module.products.signal.product_id,)
    assert assembly.source_map.acquire_sources[0][0] == acquire.id
    assert assembly.source_map.acquire_sources[0][1].kind == "acquire"


def test_multi_product_provider_keys_lower_from_public_authoring_api(
    tmp_path: Path,
) -> None:
    builder = (
        sc.module("test.products.provider-keys")
        .resource("source", requires=("scalar_signal",))
        .product("first", "second", "default")
    )
    module = builder.acquire(
        "read-all",
        "first",
        builder.products.second,
        "default",
        resource="source",
        capability="scalar_signal",
        product_keys={
            "first": "raw-first",
            builder.products.second: "raw-second",
        },
    ).build()
    template = (
        module.template("test.products.provider-keys", kind="module_products")
        .record_product("first")
        .record_product("second")
        .record_product("default")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    [acquisition] = core_acquisitions(resolved.experiment)
    assert acquisition.capability_id == "scalar_signal"
    assert {
        product.product_id.local_id: product.provider_key
        for product in acquisition.products
    } == {
        "first": "raw-first",
        "second": "raw-second",
        "default": "default",
    }


def test_acquire_rejects_invalid_provider_key_overrides() -> None:
    builder = (
        sc.module("test.products.invalid-provider-keys")
        .resource("source", requires=("scalar_signal",))
        .product("first", "second")
    )

    with pytest.raises(ValueError, match="either product_key or product_keys"):
        builder.acquire(
            "read-both",
            "first",
            resource="source",
            capability="scalar_signal",
            product_key="raw-first",
            product_keys={"first": "other-first"},
        )
    with pytest.raises(ValueError, match="unselected product"):
        builder.acquire(
            "read-both",
            "first",
            resource="source",
            capability="scalar_signal",
            product_keys={"second": "raw-second"},
        )
    with pytest.raises(ValueError, match="values must be non-empty"):
        builder.acquire(
            "read-both",
            "first",
            resource="source",
            capability="scalar_signal",
            product_keys={"first": ""},
        )


def test_explicit_instances_select_same_named_products_independently(
    tmp_path: Path,
) -> None:
    source = _product_module()
    left = source.instantiate("left")
    right = source.instantiate("right")
    root = sc.module("test.products.root").use(left, right).build()

    assert isinstance(left.products, sc.ProductOutputs)
    assert isinstance(left.products.signal, sc.ProductRef)
    assert left.products.signal.id == "left/signal"
    assert right.products["signal"].id == "right/signal"

    assembly = elaborate_module(root)
    assert [product.qualified_id for product in assembly.product_declarations] == [
        "left/signal",
        "right/signal",
    ]
    assert [port.qualified_id for port in assembly.resource_ports] == [
        "left/source",
        "right/source",
    ]

    template = (
        root.template("test.products.root", kind="module_products")
        .record_product(left.products.signal, record_id="left_signal")
        .record_product(right.products.signal, record_id="right_signal")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert [record.id for record in resolved.experiment.record_uses] == [
        "left_signal",
        "right_signal",
    ]
    uses_by_id = {use.id: use for use in resolved.experiment.product_uses}
    products_by_id = {
        product.id: product for product in resolved.experiment.product_defs
    }
    selected_products = [
        products_by_id[uses_by_id[record.product_use_id].product_id]
        for record in resolved.experiment.record_uses
    ]
    acquisitions_by_product = {
        product.product_id: (acquisition, product)
        for acquisition in core_acquisitions(resolved.experiment)
        for product in acquisition.products
    }
    selected_acquisitions = [
        acquisitions_by_product[product.id] for product in selected_products
    ]
    assert [product.id.qualified_name for product in selected_products] == [
        "left/signal",
        "right/signal",
    ]
    assert [product.product_id for _acquisition, product in selected_acquisitions] == [
        product.id for product in selected_products
    ]
    assert [
        product.provider_key for _acquisition, product in selected_acquisitions
    ] == [
        "signal",
        "signal",
    ]
    assert [
        acquisition.resource_port_id for acquisition, _product in selected_acquisitions
    ] == [
        logical_resource_port_id(SymbolId(scope=("left",), local_id="source")),
        logical_resource_port_id(SymbolId(scope=("right",), local_id="source")),
    ]
    assert [
        acquisition.capability_id for acquisition, _product in selected_acquisitions
    ] == ["scalar_signal", "scalar_signal"]
    assert [product.metadata for _acquisition, product in selected_acquisitions] == [
        {"adapter_mode": "default"},
        {"adapter_mode": "default"},
    ]


def test_nested_product_references_receive_each_parent_instance_prefix(
    tmp_path: Path,
) -> None:
    inner = _product_module().instantiate("inner")
    wrapper = sc.module("test.products.wrapper").use(inner).build()
    projected = wrapper.ir.interface.products[0]
    expected_projection = ProductId(SymbolId(scope=("inner",), local_id="signal"))
    assert projected.symbol_id == expected_projection
    assert projected.target_id == expected_projection
    outer = wrapper.instantiate("outer")
    root = sc.module("test.products.nested-root").use(outer).build()

    assert set(outer.products) == {"inner/signal"}
    nested_product = outer.products["inner/signal"]
    assert nested_product.id == "outer/inner/signal"
    assembly = elaborate_module(root)
    assert [product.qualified_id for product in assembly.product_declarations] == [
        "outer/inner/signal"
    ]

    template = (
        root.template("test.products.nested", kind="module_products")
        .record_product(nested_product, record_id="nested_signal")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    record = resolved.experiment.record_uses[0]
    use = next(
        use
        for use in resolved.experiment.product_uses
        if use.id == record.product_use_id
    )
    assert record.id == "nested_signal"
    expected_product_id = ProductId(
        SymbolId(scope=("outer", "inner"), local_id="signal")
    )
    assert use.product_id == expected_product_id
    [acquisition] = core_acquisitions(resolved.experiment)
    [acquired_product] = acquisition.products
    assert acquired_product.product_id == expected_product_id
    assert acquisition.resource_port_id == logical_resource_port_id(
        SymbolId(scope=("outer", "inner"), local_id="source")
    )
    assert acquired_product.provider_key == "signal"
    assert acquisition.capability_id == "scalar_signal"


def test_product_selection_rejects_unexposed_product() -> None:
    source = _product_module()
    selected = source.instantiate("selected")
    root = sc.module("test.products.selection-validation").use(selected).build()

    with pytest.raises(CheckFailed) as error:
        (
            root.template(
                "test.products.selection-validation",
                kind="module_products",
            )
            .record_product("signal")
            .record_product(selected.products.signal, record_id="first")
            .record_product(selected.products.signal, record_id="second")
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_product_unknown",
    ]


def test_repeated_product_selection_creates_distinct_use_occurrences(
    tmp_path: Path,
) -> None:
    source = _product_module()
    selected = source.instantiate("selected")
    root = sc.module("test.products.repeated-use").use(selected).build()
    template = (
        root.template("test.products.repeated-use", kind="module_products")
        .record_product(selected.products.signal, record_id="first")
        .record_product(selected.products.signal, record_id="second")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert len(resolved.experiment.product_uses) == 2
    assert len({use.id for use in resolved.experiment.product_uses}) == 2
    assert {use.product_id for use in resolved.experiment.product_uses} == {
        ProductId(SymbolId(scope=("selected",), local_id="signal"))
    }


def test_record_aliases_share_one_public_product_use(tmp_path: Path) -> None:
    source = _product_module()
    selected = source.instantiate("selected")
    root = sc.module("test.products.alias").use(selected).build()
    primary = sc.record_product(selected.products.signal, record_id="primary")
    secondary = sc.record_alias(
        primary,
        record_id="secondary",
        metadata={"projection": "secondary"},
    )
    template = (
        root.template("test.products.alias", kind="module_products")
        .records(primary, secondary)
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert len(resolved.experiment.product_uses) == 1
    assert [record.id for record in resolved.experiment.record_uses] == [
        "primary",
        "secondary",
    ]
    assert {record.product_use_id for record in resolved.experiment.record_uses} == {
        resolved.experiment.product_uses[0].id
    }
    assert resolved.experiment.record_uses[1].metadata == {"projection": "secondary"}


def test_authoring_compile_rejects_one_use_identity_for_two_products() -> None:
    module = (
        sc.module("test.products.conflicting-use")
        .product(
            "signal",
            "phase",
        )
        .build()
    )
    shared_id = ProductUseId("shared-use")
    selections = (
        RecordSelection(
            product_use=ProductUse(
                product_id=module.products.signal.product_id,
                id=shared_id,
            ),
            record_id="signal",
        ),
        RecordSelection(
            product_use=ProductUse(
                product_id=module.products.phase.product_id,
                id=shared_id,
            ),
            record_id="phase",
        ),
    )
    template = (
        module.template("test.products.conflicting-use", kind="module_products")
        .records(*selections)
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        compile_prepared_invocation(prepare_invocation(template.bind()))

    assert [problem.code for problem in error.value.problems] == [
        "product_use_identity_conflict"
    ]
    assert error.value.problems[0].phase is ProblemPhase.AUTHORING


def test_root_module_products_are_typed_template_refs() -> None:
    source = _product_module()

    template = (
        source.template("test.products.root-ref", kind="module_products")
        .record_product(source.products.signal)
        .build()
    )

    selection = template.record_selections[0]
    assert selection.product_id == ProductId(SymbolId(local_id="signal"))
    assert selection.product_use.product_id == selection.product_id


def test_product_refs_are_nominally_owned_by_the_selected_instance() -> None:
    left_definition = _product_module()
    right_definition = _product_module()
    foreign = left_definition.instantiate("same")
    selected = right_definition.instantiate("same")
    root = sc.module("test.products.nominal").use(selected).build()

    with pytest.raises(CheckFailed) as error:
        (
            root.template("test.products.nominal", kind="module_products")
            .record_product(foreign.products.signal)
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_product_foreign_instance"
    ]
