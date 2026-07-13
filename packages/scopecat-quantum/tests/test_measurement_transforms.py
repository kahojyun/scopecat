from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError
from scopecat import Quantity
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.point_domain import PointDomain, PointDomainId
from scopecat._compiler.products import ProductAxisDef, ProductDef
from scopecat._compiler.program import TypedProgram, product_output
from scopecat._point_domain_algebra import point_rows
from scopecat._product_identity import ProductUse, ProductUseId
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import literal_rows
from scopecat._value_expressions import verify_table_value_expr
from scopecat.config_profiles import load_config_profile
from scopecat.domain_invocation import (
    LogicalPointId,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.errors import CheckFailed
from scopecat.measurement_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformImplementationBinding,
    MeasurementTransformDef,
    MeasurementTransformId,
    MeasurementTransformPort,
    MeasurementTransformSemanticContract,
    select_host_measurement_transforms,
    verify_measurement_transform_graph,
)
from scopecat.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
)
from scopecat.value_types import Float, Scalar, Table, TableColumn

from scopecat_quantum.measurement_transforms import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _iq_product(
    *,
    dtype: MeasurementDType = "complex128",
    unit: str | None = "ratio",
    axis_kind: str = "shot",
    shot_count: int = 3,
) -> ProductDef:
    return product_output(
        "integrated-iq-shots",
        dtype=dtype,
        unit=unit,
        axes=(
            ProductAxisDef(
                id="shot",
                kind=axis_kind,
                size=shot_count,
                unit="count",
            ),
        ),
    )


def _probability_product(
    product_id: str,
    *,
    dtype: MeasurementDType = "float64",
    unit: str | None = "ratio",
) -> ProductDef:
    return product_output(
        product_id,
        dtype=dtype,
        unit=unit,
    )


def _port(
    port_id: str,
    product: ProductDef,
    use_id: str,
) -> MeasurementTransformPort:
    return MeasurementTransformPort(
        id=port_id,
        product_use_id=ProductUseId(use_id),
        product=product,
    )


def _discriminator(
    *,
    tie_policy: Literal["state_0", "state_1"] = "state_0",
    state_1_real: float = 1.0,
) -> BinaryIqDiscriminator:
    return BinaryIqDiscriminator(
        state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
        state_1_centroid=IqCentroid(real=state_1_real, imag=0.0),
        tie_policy=tie_policy,
    )


def _transform(
    *,
    discriminator: BinaryIqDiscriminator | None = None,
    iq_product: ProductDef | None = None,
    probability_0_product: ProductDef | None = None,
    probability_1_product: ProductDef | None = None,
) -> MeasurementTransformDef:
    return binary_iq_probability_transform(
        MeasurementTransformId("readout-discrimination"),
        iq_shots=_port(
            "capture/iq_shots",
            iq_product or _iq_product(),
            "iq-use",
        ),
        probability_0=_port(
            "capture/probability_0",
            probability_0_product or _probability_product("probability-0"),
            "p0-use",
        ),
        probability_1=_port(
            "capture/probability_1",
            probability_1_product or _probability_product("probability-1"),
            "p1-use",
        ),
        discriminator=discriminator or _discriminator(),
    )


def _logical_point_id() -> LogicalPointId:
    return LogicalPointId(
        PointDomainId(program_id="binary-iq-test", domain_id="points"),
        0,
    )


def _linked_transform_contracts() -> tuple[
    MaterializedLinkedPoints,
    tuple[ProductDef, ProductDef, ProductDef],
    tuple[ProductUse, ...],
]:
    point_type = Table(
        columns=(TableColumn("coordinate", Scalar(Float())),),
        min_rows=1,
        max_rows=1,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(({"coordinate": 1.0},)),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    products = (
        _iq_product(),
        _probability_product("probability-0"),
        _probability_product("probability-1"),
    )
    uses = tuple(
        ProductUse(
            product_id=product.id,
            id=ProductUseId(f"{wiring}-{role}"),
        )
        for wiring in ("left", "right")
        for role, product in zip(("iq", "p0", "p1"), products, strict=True)
    )
    program = TypedProgram(
        id="binary-iq-transform-test",
        kind="binary_iq_transform_test",
        point_domain=point_domain,
        product_defs=products,
        product_uses=uses,
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    return (
        materialize_linked_points(link_program(program, environment)),
        products,
        uses,
    )


def _wired_transform(
    products: tuple[ProductDef, ProductDef, ProductDef],
    uses: tuple[ProductUse, ProductUse, ProductUse],
) -> MeasurementTransformDef:
    return binary_iq_probability_transform(
        MeasurementTransformId("readout-discrimination"),
        iq_shots=MeasurementTransformPort("caller-iq", uses[0].id, products[0]),
        probability_0=MeasurementTransformPort(
            "caller-p0",
            uses[1].id,
            products[1],
        ),
        probability_1=MeasurementTransformPort(
            "caller-p1",
            uses[2].id,
            products[2],
        ),
        discriminator=_discriminator(),
    )


@pytest.mark.parametrize(
    "centroid",
    (
        {"real": math.inf, "imag": 0.0},
        {"real": 0.0, "imag": math.nan},
    ),
)
def test_binary_iq_discriminator_requires_finite_ratio_centroids(
    centroid: dict[str, float],
) -> None:
    with pytest.raises(ValidationError, match="centroids must be finite"):
        BinaryIqDiscriminator(
            state_0_centroid=IqCentroid.model_validate(centroid),
            state_1_centroid=IqCentroid(real=1.0, imag=0.0),
        )


def test_binary_iq_discriminator_requires_distinct_centroids() -> None:
    centroid = IqCentroid(real=0.25, imag=-0.5)

    with pytest.raises(ValidationError, match="centroids must be distinct"):
        BinaryIqDiscriminator(
            state_0_centroid=centroid,
            state_1_centroid=centroid,
        )


def test_binary_iq_builder_retains_complete_host_semantics() -> None:
    transform = _transform(discriminator=_discriminator(tie_policy="state_1"))

    assert transform.rate == "point"
    assert [port.id for port in transform.inputs] == ["iq_shots"]
    assert [port.id for port in transform.outputs] == [
        "probability_0",
        "probability_1",
    ]
    assert transform.semantic.id == (
        "scopecat_quantum.readout.binary_iq_discrimination"
    )
    assert transform.semantic.version == "1"
    assert transform.semantic.portability == "host_only"
    assert transform.semantic.parameters == {
        "discriminator": {
            "schema_version": "scopecat_quantum.binary_iq_discriminator.v1",
            "state_0_centroid": {"real": -1.0, "imag": 0.0, "unit": "ratio"},
            "state_1_centroid": {"real": 1.0, "imag": 0.0, "unit": "ratio"},
            "tie_policy": "state_1",
        },
    }

    changed_centroid = _transform(discriminator=_discriminator(state_1_real=2.0))
    changed_tie = _transform(discriminator=_discriminator(tie_policy="state_1"))
    assert (
        transform.semantic.contract_fingerprint
        != changed_centroid.semantic.contract_fingerprint
    )
    assert (
        _transform().semantic.contract_fingerprint
        != changed_tie.semantic.contract_fingerprint
    )


def test_semantic_identity_is_independent_of_product_use_wiring() -> None:
    linked_points, products, uses = _linked_transform_contracts()
    left = _wired_transform(products, (uses[0], uses[1], uses[2]))
    right = _wired_transform(products, (uses[3], uses[4], uses[5]))

    left_graph = verify_measurement_transform_graph(linked_points, (left,))
    right_graph = verify_measurement_transform_graph(linked_points, (right,))

    assert left.semantic.contract_fingerprint == right.semantic.contract_fingerprint
    assert left.semantic.parameters == right.semantic.parameters
    assert left_graph.contract_fingerprint != right_graph.contract_fingerprint


@pytest.mark.parametrize(
    "invalid_dimension",
    ("semantic_parameters", "port_role", "product_schema"),
)
def test_reference_implementation_rejects_invalid_contract_before_kernel(
    invalid_dimension: str,
) -> None:
    linked_points, products, uses = _linked_transform_contracts()
    valid = _wired_transform(products, (uses[0], uses[1], uses[2]))
    if invalid_dimension == "semantic_parameters":
        invalid = replace(
            valid,
            semantic=MeasurementTransformSemanticContract(
                id=valid.semantic.id,
                version=valid.semantic.version,
                portability="host_only",
                parameters={
                    "discriminator": _discriminator().model_dump(mode="json"),
                    "unexpected": True,
                },
            ),
        )
    elif invalid_dimension == "port_role":
        invalid = replace(
            valid,
            inputs=(
                MeasurementTransformPort(
                    "renamed_iq",
                    valid.inputs[0].product_use_id,
                    valid.inputs[0].product,
                ),
            ),
        )
    else:
        invalid = replace(
            valid,
            inputs=(
                MeasurementTransformPort(
                    "iq_shots",
                    uses[1].id,
                    products[1],
                ),
            ),
            outputs=(
                MeasurementTransformPort(
                    "probability_0",
                    uses[0].id,
                    products[0],
                ),
                valid.outputs[1],
            ),
        )
    graph = verify_measurement_transform_graph(linked_points, (invalid,))
    reference = binary_iq_probability_host_implementation()
    kernel_calls = 0

    def forbidden_kernel(call: HostMeasurementTransformCall):
        nonlocal kernel_calls
        kernel_calls += 1
        return reference.kernel(call)

    with pytest.raises(CheckFailed) as captured:
        select_host_measurement_transforms(
            graph,
            (replace(reference, kernel=forbidden_kernel),),
            (
                HostMeasurementTransformImplementationBinding(
                    invalid.id,
                    reference.id,
                ),
            ),
        )

    assert kernel_calls == 0
    assert {problem.code for problem in captured.value.problems} == {
        "measurement_transform_host_capability_rejected"
    }


@pytest.mark.parametrize(
    "product",
    (
        _iq_product(dtype="float64"),
        _iq_product(unit=None),
        _iq_product(axis_kind="sample"),
        _iq_product().model_copy(update={"axes": ()}),
    ),
)
def test_binary_iq_builder_rejects_incompatible_input_contract(
    product: ProductDef,
) -> None:
    with pytest.raises(ValueError, match="complex128 ratio product"):
        _transform(iq_product=product)


@pytest.mark.parametrize(
    "product",
    (
        _probability_product("probability-0", dtype="complex128"),
        _probability_product("probability-0", unit=None),
        _probability_product("probability-0").model_copy(
            update={"axes": _iq_product().axes}
        ),
    ),
)
def test_binary_iq_builder_rejects_incompatible_output_contract(
    product: ProductDef,
) -> None:
    with pytest.raises(ValueError, match="scalar float64 ratio observable"):
        _transform(probability_0_product=product)


def test_reference_host_implementation_classifies_shots_and_applies_tie_policy() -> (
    None
):
    transform = _transform(discriminator=_discriminator(tie_policy="state_1"))
    implementation = binary_iq_probability_host_implementation()
    call = HostMeasurementTransformCall(
        transform_id=transform.id,
        semantic=transform.semantic,
        logical_point_id=_logical_point_id(),
        point_index=0,
        input_ports=transform.inputs,
        output_ports=transform.outputs,
        inputs={
            transform.inputs[0].id: MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[3],
                values=[
                    ComplexQuantity(real=-0.9, imag=0.0, unit="ratio"),
                    ComplexQuantity(real=0.9, imag=0.0, unit="ratio"),
                    ComplexQuantity(real=0.0, imag=0.0, unit="ratio"),
                ],
            )
        },
    )

    outputs = implementation.kernel(call)

    assert implementation.semantic_id == transform.semantic.id
    assert implementation.semantic_version == transform.semantic.version
    assert implementation.rate == "point"
    assert set(outputs) == {"probability_0", "probability_1"}
    probability_0 = outputs["probability_0"]
    probability_1 = outputs["probability_1"]
    assert isinstance(probability_0, Quantity)
    assert isinstance(probability_1, Quantity)
    assert probability_0.value == pytest.approx(1 / 3)
    assert probability_1.value == pytest.approx(2 / 3)
    assert probability_0.unit == "ratio"
    assert probability_1.unit == "ratio"
    assert probability_0.value + probability_1.value == 1.0


def test_reference_host_implementation_rejects_non_finite_shots() -> None:
    transform = _transform()
    implementation = binary_iq_probability_host_implementation()
    call = HostMeasurementTransformCall(
        transform_id=transform.id,
        semantic=transform.semantic,
        logical_point_id=_logical_point_id(),
        point_index=0,
        input_ports=transform.inputs,
        output_ports=transform.outputs,
        inputs={
            transform.inputs[0].id: MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[1],
                values=[ComplexQuantity(real=math.inf, imag=0.0, unit="ratio")],
            )
        },
    )

    with pytest.raises(ValueError, match="finite ratio IQ shots"):
        implementation.kernel(call)
