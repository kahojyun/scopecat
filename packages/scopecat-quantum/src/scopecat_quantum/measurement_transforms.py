"""Hardware-independent quantum measurement-transform building blocks."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from scopecat import MeasurementTransform, Quantity, measurement_transform
from scopecat.measurements.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.sdk.domain.measurements import (
    DomainHostTransformCall,
    DomainHostTransformImplementation,
    DomainMeasurementTransform,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)

_BINARY_IQ_SEMANTIC_ID = "scopecat_quantum.readout.binary_iq_discrimination"
_BINARY_IQ_SEMANTIC_VERSION = "1"
_BINARY_IQ_IMPLEMENTATION_ID = (
    "scopecat_quantum.readout.binary_iq_discrimination.reference"
)
_BINARY_IQ_IMPLEMENTATION_FINGERPRINT = (
    "scopecat-quantum.binary-iq-nearest-centroid.python.v1"
)
_IQ_SHOTS_ROLE = "iq_shots"
_PROBABILITY_0_ROLE = "probability_0"
_PROBABILITY_1_ROLE = "probability_1"


class IqCentroid(BaseModel):
    """One finite centroid in dimensionless integrated-IQ space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    real: float
    imag: float
    unit: Literal["ratio"] = "ratio"

    @model_validator(mode="after")
    def validate_finite(self) -> IqCentroid:
        if not (math.isfinite(self.real) and math.isfinite(self.imag)):
            msg = "binary IQ discriminator centroids must be finite"
            raise ValueError(msg)
        return self


class BinaryIqDiscriminator(BaseModel):
    """Host nearest-centroid semantics for binary integrated-IQ shots.

    A shot is assigned to the state with the smaller squared Euclidean
    distance. Exact equidistance is resolved by ``tie_policy``. Numerical
    precision and rounding are not yet part of an offload contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat_quantum.binary_iq_discriminator.v1"] = (
        "scopecat_quantum.binary_iq_discriminator.v1"
    )
    state_0_centroid: IqCentroid
    state_1_centroid: IqCentroid
    tie_policy: Literal["state_0", "state_1"] = "state_0"

    @model_validator(mode="after")
    def validate_distinct_centroids(self) -> BinaryIqDiscriminator:
        state_0 = self.state_0_centroid
        state_1 = self.state_1_centroid
        if state_0.real == state_1.real and state_0.imag == state_1.imag:
            msg = "binary IQ discriminator centroids must be distinct"
            raise ValueError(msg)
        return self


def binary_iq_probability_transform(
    transform_id: str,
    *,
    iq_shots: str,
    probability_0: str,
    probability_1: str,
    discriminator: BinaryIqDiscriminator,
) -> MeasurementTransform:
    """Declare one authored point-local IQ-shot discrimination transform."""

    if not transform_id:
        msg = "binary IQ probability transform ids must be non-empty"
        raise ValueError(msg)
    product_bindings = {
        _IQ_SHOTS_ROLE: iq_shots,
        _PROBABILITY_0_ROLE: probability_0,
        _PROBABILITY_1_ROLE: probability_1,
    }
    for role, product_id in product_bindings.items():
        if not product_id:
            msg = f"binary IQ {role} product ids must be non-empty"
            raise ValueError(msg)
    if len(set(product_bindings.values())) != len(product_bindings):
        msg = "binary IQ probability transform products must be distinct"
        raise ValueError(msg)
    return measurement_transform(
        transform_id,
        semantic=_binary_iq_semantic(discriminator),
        rate="point",
        inputs={_IQ_SHOTS_ROLE: iq_shots},
        outputs={
            _PROBABILITY_0_ROLE: probability_0,
            _PROBABILITY_1_ROLE: probability_1,
        },
    )


def _binary_iq_semantic(
    discriminator: BinaryIqDiscriminator,
) -> MeasurementTransformSemanticContract:
    return MeasurementTransformSemanticContract(
        id=_BINARY_IQ_SEMANTIC_ID,
        version=_BINARY_IQ_SEMANTIC_VERSION,
        portability="host_only",
        parameters={
            "discriminator": discriminator.model_dump(mode="json"),
        },
    )


def binary_iq_probability_host_implementation() -> DomainHostTransformImplementation:
    """Return the host-only pure-Python nearest-centroid realization."""

    return DomainHostTransformImplementation(
        id=_BINARY_IQ_IMPLEMENTATION_ID,
        semantic_id=_BINARY_IQ_SEMANTIC_ID,
        semantic_version=_BINARY_IQ_SEMANTIC_VERSION,
        rate="point",
        implementation_fingerprint=_BINARY_IQ_IMPLEMENTATION_FINGERPRINT,
        validate_transform=_validate_binary_iq_probability_transform,
        kernel=_binary_iq_probability_kernel,
    )


def _binary_iq_probability_kernel(
    call: DomainHostTransformCall,
) -> dict[str, MeasurementValue]:
    semantic = call.semantic
    if (
        semantic.id != _BINARY_IQ_SEMANTIC_ID
        or semantic.version != _BINARY_IQ_SEMANTIC_VERSION
    ):
        msg = "binary IQ host implementation received incompatible semantics"
        raise ValueError(msg)
    discriminator = _discriminator_from_semantic(semantic)
    _validate_call_ports(call)
    if set(call.inputs) != {_IQ_SHOTS_ROLE}:
        msg = "binary IQ host implementation requires its exact IQ-shot input"
        raise ValueError(msg)
    value = call.inputs[_IQ_SHOTS_ROLE]
    if not isinstance(value, MeasurementArray):
        msg = "binary IQ host implementation requires a MeasurementArray"
        raise TypeError(msg)
    if value.dtype != "complex128" or value.unit != "ratio" or len(value.shape) != 1:
        msg = "binary IQ host implementation requires complex128 ratio [shot] values"
        raise ValueError(msg)
    if value.shape[0] <= 0:
        msg = "binary IQ host implementation requires at least one shot"
        raise ValueError(msg)
    shots = value.values
    state_0_count = 0
    for shot in shots:
        if not isinstance(shot, ComplexQuantity):
            msg = "binary IQ host implementation requires complex shot leaves"
            raise TypeError(msg)
        if shot.unit != "ratio" or not (
            math.isfinite(shot.real) and math.isfinite(shot.imag)
        ):
            msg = "binary IQ host implementation requires finite ratio IQ shots"
            raise ValueError(msg)
        if _classify_shot(shot, discriminator) == 0:
            state_0_count += 1

    probability_0 = state_0_count / len(shots)
    probability_1 = 1.0 - probability_0
    return {
        _PROBABILITY_0_ROLE: Quantity(value=probability_0, unit="ratio"),
        _PROBABILITY_1_ROLE: Quantity(value=probability_1, unit="ratio"),
    }


def _discriminator_from_semantic(
    semantic: MeasurementTransformSemanticContract,
) -> BinaryIqDiscriminator:
    if (
        semantic.id != _BINARY_IQ_SEMANTIC_ID
        or semantic.version != _BINARY_IQ_SEMANTIC_VERSION
        or semantic.portability != "host_only"
    ):
        msg = "binary IQ semantics require the supported host-only semantic family"
        raise ValueError(msg)
    parameters = semantic.parameters
    if set(parameters) != {"discriminator"}:
        msg = "binary IQ semantics require the exact discriminator parameter schema"
        raise ValueError(msg)
    discriminator_data = parameters.get("discriminator")
    if not isinstance(discriminator_data, Mapping):
        msg = "binary IQ semantics require discriminator parameters"
        raise ValueError(msg)
    return BinaryIqDiscriminator.model_validate(discriminator_data)


def _validate_binary_iq_probability_transform(
    transform: DomainMeasurementTransform,
) -> None:
    _discriminator_from_semantic(transform.semantic)
    if transform.rate != "point":
        msg = "binary IQ host implementation requires point rate"
        raise ValueError(msg)
    if tuple(port.id for port in transform.inputs) != (_IQ_SHOTS_ROLE,):
        msg = "binary IQ transform requires the exact iq_shots input role"
        raise ValueError(msg)
    if {port.id for port in transform.outputs} != {
        _PROBABILITY_0_ROLE,
        _PROBABILITY_1_ROLE,
    } or len(transform.outputs) != 2:
        msg = "binary IQ transform requires exact probability_0/1 output roles"
        raise ValueError(msg)
    input_port = transform.inputs[0]
    outputs = {port.id: port for port in transform.outputs}
    _validate_iq_shot_input(input_port)
    _validate_probability_output(
        outputs[_PROBABILITY_0_ROLE],
        subject=_PROBABILITY_0_ROLE,
    )
    _validate_probability_output(
        outputs[_PROBABILITY_1_ROLE],
        subject=_PROBABILITY_1_ROLE,
    )
    if (
        len(
            {
                input_port.product.id,
                outputs[_PROBABILITY_0_ROLE].product.id,
                outputs[_PROBABILITY_1_ROLE].product.id,
            }
        )
        != 3
    ):
        msg = "binary IQ probability transform products must be distinct"
        raise ValueError(msg)
    product_uses = (
        input_port.product_use,
        *outputs[_PROBABILITY_0_ROLE].product_uses,
        *outputs[_PROBABILITY_1_ROLE].product_uses,
    )
    if len({id(product_use) for product_use in product_uses}) != len(product_uses):
        msg = "binary IQ probability transform product uses must be distinct"
        raise ValueError(msg)


def _validate_call_ports(call: DomainHostTransformCall) -> None:
    if tuple(port.id for port in call.input_ports) != (_IQ_SHOTS_ROLE,):
        msg = "binary IQ host call requires the exact iq_shots input role"
        raise ValueError(msg)
    outputs = {port.id: port for port in call.output_ports}
    if (
        set(outputs) != {_PROBABILITY_0_ROLE, _PROBABILITY_1_ROLE}
        or len(call.output_ports) != 2
    ):
        msg = "binary IQ host call requires exact probability_0/1 output roles"
        raise ValueError(msg)
    _validate_iq_shot_input(call.input_ports[0])
    _validate_probability_output(
        outputs[_PROBABILITY_0_ROLE],
        subject=_PROBABILITY_0_ROLE,
    )
    _validate_probability_output(
        outputs[_PROBABILITY_1_ROLE],
        subject=_PROBABILITY_1_ROLE,
    )


def _classify_shot(
    shot: ComplexQuantity,
    discriminator: BinaryIqDiscriminator,
) -> Literal[0, 1]:
    state_0 = discriminator.state_0_centroid
    state_1 = discriminator.state_1_centroid
    distance_0 = (shot.real - state_0.real) ** 2 + (shot.imag - state_0.imag) ** 2
    distance_1 = (shot.real - state_1.real) ** 2 + (shot.imag - state_1.imag) ** 2
    if distance_0 < distance_1:
        return 0
    if distance_1 < distance_0:
        return 1
    return 0 if discriminator.tie_policy == "state_0" else 1


def _validate_iq_shot_input(port: DomainTransformInputPort) -> None:
    product = port.product
    axes = product.axes
    if (
        product.kind != "observable"
        or product.dtype != "complex128"
        or product.unit != "ratio"
        or len(axes) != 1
        or axes[0].kind != "shot"
        or axes[0].size <= 0
    ):
        msg = (
            "binary IQ input must be an observable complex128 ratio product "
            "with one non-empty shot axis"
        )
        raise ValueError(msg)


def _validate_probability_output(
    port: DomainTransformOutputPort,
    *,
    subject: str,
) -> None:
    product = port.product
    if (
        product.kind != "observable"
        or product.dtype != "float64"
        or product.unit != "ratio"
        or product.axes
    ):
        msg = f"binary IQ {subject} must be a scalar float64 ratio observable"
        raise ValueError(msg)


__all__ = [
    "BinaryIqDiscriminator",
    "IqCentroid",
    "binary_iq_probability_host_implementation",
    "binary_iq_probability_transform",
]
