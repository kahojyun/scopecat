from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring._module_composition import assemble_module_internal
from scopecat.authoring._resolution import resolve_experiment
from scopecat.errors import CheckFailed
from tests.support.authoring import load_config


def _product_module() -> sc.ExperimentModule:
    return (
        sc.module("test.products.source")
        .resource("source")
        .product("signal", resource="source", unit="ratio")
        .build()
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

    assembly = assemble_module_internal(root)
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
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert [record.id for record in resolved.experiment.records] == [
        "left_signal",
        "right_signal",
    ]
    assert [
        record.metadata["product_id"] for record in resolved.experiment.records
    ] == ["left/signal", "right/signal"]
    assert [record.product_key for record in resolved.experiment.records] == [
        "signal",
        "signal",
    ]
    assert [record.resource for record in resolved.experiment.records] == [
        "left/source",
        "right/source",
    ]


def test_nested_product_references_receive_each_parent_instance_prefix(
    tmp_path: Path,
) -> None:
    inner = _product_module().instantiate("inner")
    wrapper = sc.module("test.products.wrapper").use(inner).build()
    outer = wrapper.instantiate("outer")
    root = sc.module("test.products.nested-root").use(outer).build()

    assert set(outer.products) == {"inner/signal"}
    nested_product = outer.products["inner/signal"]
    assert nested_product.id == "outer/inner/signal"
    assembly = assemble_module_internal(root)
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
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert resolved.experiment.records[0].id == "nested_signal"
    assert resolved.experiment.records[0].metadata["product_id"] == (
        "outer/inner/signal"
    )


def test_product_ref_selection_still_checks_membership_and_duplicates() -> None:
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
        "module_product_selection_duplicate",
    ]


def test_legacy_invocation_requires_explicit_identity_for_products() -> None:
    invocation = _product_module()()

    with pytest.raises(ValueError, match=r"use module\.instantiate"):
        _ = invocation.products


def test_root_module_products_are_typed_template_refs() -> None:
    source = _product_module()

    template = (
        source.template("test.products.root-ref", kind="module_products")
        .record_product(source.products.signal)
        .build()
    )

    assert template.record_selections[0].product_id == "signal"


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
