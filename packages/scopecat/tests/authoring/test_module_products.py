from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring._record_intents import ProductSelectionIntent
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
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
        .resource("source")
        .product(
            "signal",
            resource="source",
            unit="ratio",
            producer_metadata={"adapter_mode": "default"},
        )
        .build()
    )


def test_inline_record_lowers_logical_and_producer_metadata_independently(
    tmp_path: Path,
) -> None:
    module = (
        sc.module("test.products.metadata")
        .record(
            "signal",
            metadata={"schema_owner": "analysis"},
            producer_metadata={"adapter_mode": "fast"},
        )
        .build()
    )
    resolved = resolve_experiment(
        module.template(
            "test.products.metadata",
            kind="module_products",
        )
        .build()
        .bind(),
        config_profile=load_config(),
    )

    assert resolved.experiment.product_defs[0].metadata == {"schema_owner": "analysis"}
    assert resolved.experiment.instrument_product_producers[0].metadata == {
        "adapter_mode": "fast"
    }


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
    assert [product.qualified_id for product in assembly.product_ports] == [
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
    producers_by_product = {
        producer.product_id: producer
        for producer in resolved.experiment.instrument_product_producers
    }
    selected_producers = [
        producers_by_product[product.id] for product in selected_products
    ]
    assert [product.id.qualified_name for product in selected_products] == [
        "left/signal",
        "right/signal",
    ]
    assert [producer.product_id for producer in selected_producers] == [
        product.id for product in selected_products
    ]
    assert [producer.id for producer in selected_producers] == [
        ProductProducerId(product.id.symbol) for product in selected_products
    ]
    assert [producer.provider_key for producer in selected_producers] == [
        "signal",
        "signal",
    ]
    assert [producer.resource_target for producer in selected_producers] == [
        logical_resource_port_id(SymbolId(scope=("left",), local_id="source")),
        logical_resource_port_id(SymbolId(scope=("right",), local_id="source")),
    ]
    assert [producer.capability for producer in selected_producers] == [None, None]
    assert [producer.metadata for producer in selected_producers] == [
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
    assert not hasattr(projected, "resource")
    assert not hasattr(projected, "axes")
    outer = wrapper.instantiate("outer")
    root = sc.module("test.products.nested-root").use(outer).build()

    assert set(outer.products) == {"inner/signal"}
    nested_product = outer.products["inner/signal"]
    assert nested_product.id == "outer/inner/signal"
    assembly = elaborate_module(root)
    assert [product.qualified_id for product in assembly.product_ports] == [
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
    producer = resolved.experiment.instrument_product_producers[0]
    assert producer.product_id == expected_product_id
    assert producer.id == ProductProducerId(expected_product_id.symbol)
    assert producer.resource_target == logical_resource_port_id(
        SymbolId(scope=("outer", "inner"), local_id="source")
    )
    assert producer.provider_key == "signal"
    assert producer.capability is None


def test_product_ref_selection_still_checks_membership() -> None:
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
        ProductSelectionIntent(
            product_use=ProductUse(
                product_id=module.products.signal.product_id,
                id=shared_id,
            ),
            record_id="signal",
        ),
        ProductSelectionIntent(
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


def test_module_is_not_an_anonymous_product_invocation_factory() -> None:
    assert not callable(_product_module())


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
