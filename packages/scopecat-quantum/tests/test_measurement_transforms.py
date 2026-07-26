from __future__ import annotations

import math
from dataclasses import replace
from typing import Literal

import pytest
from pydantic import ValidationError
from scopecat import MeasurementTransform, Quantity
from scopecat.kernel.product_identity import product_id as product_id_
from scopecat.measurements.products import ProductAxisDef, ProductDef
from scopecat.measurements.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
    MeasurementValue,
)
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.sdk.domain.measurements import (
    DomainHostTransformCall,
    DomainMeasurementTransform,
)
from scopecat.sdk.domain.view import (
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)

from scopecat_quantum.measurement_transforms import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
)


def _iq_product(
    *,
    dtype: MeasurementDType = "complex128",
    unit: str | None = "ratio",
    axis_kind: str = "shot",
    shot_count: int = 3,
) -> ProductDef:
    return ProductDef(
        id=product_id_("integrated-iq-shots"),
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
    return ProductDef(id=product_id_(product_id), dtype=dtype, unit=unit)


def _product_view(product: ProductDef) -> DomainProductContractView:
    return DomainProductContractView(
        id=product.id.qualified_name,
        unit=product.unit,
        dtype=product.dtype,
        axes=tuple(
            DomainProductAxisView(
                id=axis.id,
                kind=axis.kind,
                size=axis.size,
                unit=axis.unit,
                metadata=axis.metadata,
            )
            for axis in product.axes
        ),
        metadata=product.metadata,
    )


def _product_use(product: ProductDef, use_id: str) -> DomainProductUseRef:
    return DomainProductUseRef(
        id=use_id,
        product=_product_view(product),
        native=object(),
    )


def _point() -> DomainPointRef:
    return DomainPointRef(
        id="binary-iq-test:point:0",
        ordinal=0,
        native=object(),
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


def _authored_transform(
    *,
    discriminator: BinaryIqDiscriminator | None = None,
    wiring: str = "default",
) -> MeasurementTransform:
    return binary_iq_probability_transform(
        "readout-discrimination",
        iq_shots=f"{wiring}-iq",
        probability_0=f"{wiring}-p0",
        probability_1=f"{wiring}-p1",
        discriminator=discriminator or _discriminator(),
    )


def _domain_transform(
    *,
    discriminator: BinaryIqDiscriminator | None = None,
    iq_product: ProductDef | None = None,
    probability_0_product: ProductDef | None = None,
    probability_1_product: ProductDef | None = None,
    wiring: str = "default",
) -> DomainMeasurementTransform:
    authored = _authored_transform(
        discriminator=discriminator,
        wiring=wiring,
    )
    iq_product_view = _product_view(iq_product or _iq_product())
    probability_0_product_view = _product_view(
        probability_0_product or _probability_product("probability-0")
    )
    probability_1_product_view = _product_view(
        probability_1_product or _probability_product("probability-1")
    )
    iq_use = _product_use(iq_product or _iq_product(), f"{wiring}-iq")
    probability_0_use = _product_use(
        probability_0_product or _probability_product("probability-0"),
        f"{wiring}-p0",
    )
    probability_1_use = _product_use(
        probability_1_product or _probability_product("probability-1"),
        f"{wiring}-p1",
    )
    return DomainMeasurementTransform(
        id=authored.id,
        semantic=authored.semantic,
        inputs=(
            DomainTransformInputPort(
                id="iq_shots",
                product_use=iq_use,
                product=iq_product_view,
            ),
        ),
        outputs=(
            DomainTransformOutputPort(
                id="probability_0",
                product=probability_0_product_view,
                product_uses=(probability_0_use,),
            ),
            DomainTransformOutputPort(
                id="probability_1",
                product=probability_1_product_view,
                product_uses=(probability_1_use,),
            ),
        ),
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


def test_binary_iq_builder_retains_complete_authored_semantics_and_edges() -> None:
    transform = _authored_transform(discriminator=_discriminator(tie_policy="state_1"))

    assert isinstance(transform, MeasurementTransform)
    assert [(role, product.local_id) for role, product in transform.input_bindings] == [
        ("iq_shots", "default-iq")
    ]
    assert [
        (role, product.local_id) for role, product in transform.output_bindings
    ] == [
        ("probability_0", "default-p0"),
        ("probability_1", "default-p1"),
    ]
    assert transform.semantic.id == (
        "scopecat_quantum.readout.binary_iq_discrimination"
    )
    assert transform.semantic.version == "1"
    assert transform.semantic.parameters == {
        "discriminator": {
            "state_0_centroid": {"real": -1.0, "imag": 0.0, "unit": "ratio"},
            "state_1_centroid": {"real": 1.0, "imag": 0.0, "unit": "ratio"},
            "tie_policy": "state_1",
        },
    }

    changed_centroid = _authored_transform(
        discriminator=_discriminator(state_1_real=2.0)
    )
    changed_tie = _authored_transform(
        discriminator=_discriminator(tie_policy="state_1")
    )
    assert transform.semantic != changed_centroid.semantic
    assert _authored_transform().semantic != changed_tie.semantic


def test_semantic_identity_is_independent_of_authored_product_wiring() -> None:
    left = _authored_transform(wiring="left")
    right = _authored_transform(wiring="right")

    assert left.semantic == right.semantic
    assert left.semantic.parameters == right.semantic.parameters
    assert left.input_bindings != right.input_bindings
    assert left.output_bindings != right.output_bindings


@pytest.mark.parametrize(
    "invalid_dimension",
    ("semantic_parameters", "port_role", "product_schema"),
)
def test_reference_implementation_rejects_invalid_sdk_contract(
    invalid_dimension: str,
) -> None:
    valid = _domain_transform()
    if invalid_dimension == "semantic_parameters":
        invalid = DomainMeasurementTransform(
            id=valid.id,
            semantic=MeasurementTransformSemanticContract(
                id=valid.semantic.id,
                version=valid.semantic.version,
                parameters={
                    "discriminator": _discriminator().model_dump(mode="json"),
                    "unexpected": True,
                },
            ),
            inputs=valid.inputs,
            outputs=valid.outputs,
        )
    elif invalid_dimension == "port_role":
        invalid = DomainMeasurementTransform(
            id=valid.id,
            semantic=valid.semantic,
            inputs=(
                DomainTransformInputPort(
                    id="renamed_iq",
                    product_use=valid.inputs[0].product_use,
                    product=valid.inputs[0].product,
                ),
            ),
            outputs=valid.outputs,
        )
    else:
        invalid = DomainMeasurementTransform(
            id=valid.id,
            semantic=valid.semantic,
            inputs=(
                DomainTransformInputPort(
                    id="iq_shots",
                    product_use=valid.outputs[0].product_uses[0],
                    product=valid.outputs[0].product,
                ),
            ),
            outputs=(
                DomainTransformOutputPort(
                    id="probability_0",
                    product=valid.inputs[0].product,
                    product_uses=(valid.inputs[0].product_use,),
                ),
                valid.outputs[1],
            ),
        )

    with pytest.raises(ValueError, match="binary IQ"):
        binary_iq_probability_host_implementation().validate_transform(invalid)


@pytest.mark.parametrize(
    "product",
    (
        _iq_product(dtype="float64"),
        _iq_product(unit=None),
        _iq_product(axis_kind="sample"),
        replace(_iq_product(), axes=()),
    ),
)
def test_reference_implementation_rejects_incompatible_input_contract(
    product: ProductDef,
) -> None:
    with pytest.raises(ValueError, match="complex128 ratio product"):
        binary_iq_probability_host_implementation().validate_transform(
            _domain_transform(iq_product=product)
        )


@pytest.mark.parametrize(
    "product",
    (
        _probability_product("probability-0", dtype="complex128"),
        _probability_product("probability-0", unit=None),
        replace(_probability_product("probability-0"), axes=_iq_product().axes),
    ),
)
def test_reference_implementation_rejects_incompatible_output_contract(
    product: ProductDef,
) -> None:
    with pytest.raises(ValueError, match="scalar float64 ratio product"):
        binary_iq_probability_host_implementation().validate_transform(
            _domain_transform(probability_0_product=product)
        )


def test_reference_host_implementation_classifies_shots_and_applies_tie_policy() -> (
    None
):
    transform = _domain_transform(discriminator=_discriminator(tie_policy="state_1"))
    implementation = binary_iq_probability_host_implementation()
    call = DomainHostTransformCall(
        transform=transform,
        points=(_point(),),
        inputs={
            transform.inputs[0].id: (
                MeasurementArray(
                    dtype="complex128",
                    unit="ratio",
                    shape=[3],
                    values=[
                        ComplexQuantity(real=-0.9, imag=0.0, unit="ratio"),
                        ComplexQuantity(real=0.9, imag=0.0, unit="ratio"),
                        ComplexQuantity(real=0.0, imag=0.0, unit="ratio"),
                    ],
                ),
            )
        },
    )

    outputs = implementation.kernel(call)

    assert implementation.semantic_id == transform.semantic.id
    assert implementation.semantic_version == transform.semantic.version
    assert set(outputs) == {"probability_0", "probability_1"}
    [probability_0] = outputs["probability_0"]
    [probability_1] = outputs["probability_1"]
    assert isinstance(probability_0, Quantity)
    assert isinstance(probability_1, Quantity)
    assert probability_0.value == pytest.approx(1 / 3)
    assert probability_1.value == pytest.approx(2 / 3)
    assert probability_0.unit == "ratio"
    assert probability_1.unit == "ratio"
    assert probability_0.value + probability_1.value == 1.0


def test_reference_host_implementation_rejects_non_finite_shots() -> None:
    transform = _domain_transform()
    implementation = binary_iq_probability_host_implementation()
    call = DomainHostTransformCall(
        transform=transform,
        points=(_point(),),
        inputs={
            transform.inputs[0].id: (
                MeasurementArray(
                    dtype="complex128",
                    unit="ratio",
                    shape=[1],
                    values=[ComplexQuantity(real=math.inf, imag=0.0, unit="ratio")],
                ),
            )
        },
    )

    with pytest.raises(ValueError, match="finite ratio IQ shots"):
        implementation.kernel(call)


def test_domain_host_call_snapshots_sdk_measurement_inputs() -> None:
    transform = _domain_transform()
    value = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[1],
        values=[ComplexQuantity(real=-1.0, imag=0.0, unit="ratio")],
    )
    raw: dict[str, tuple[MeasurementValue, ...]] = {"iq_shots": (value,)}

    call = DomainHostTransformCall(transform, (_point(),), raw)
    raw.clear()

    assert set(call.inputs) == {"iq_shots"}
