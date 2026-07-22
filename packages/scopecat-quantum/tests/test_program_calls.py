from __future__ import annotations

import inspect
from typing import Annotated, assert_type, cast

import pytest
import scopecat as sc

from scopecat_quantum import authoring
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.gates import GateParameterKind
from scopecat_quantum.measurement_transforms import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_transform,
)


def test_program_decorator_infers_ports_identity_description_and_results() -> None:
    x = authoring.single_qubit_gate("x")
    elaborations = 0

    @authoring.program(id="test.quantum.decorated")
    def x_count(
        qubit: authoring.Qubit,
        count: Annotated[int, GateParameterKind.INTEGER],
    ) -> authoring.QuantumFragment:
        """Repeat X and measure once."""

        nonlocal elaborations
        elaborations += 1
        return authoring.sequence(
            authoring.repeat(x(qubit), count),
            authoring.measure(qubit, result="iq_shots"),
        )

    assert elaborations == 1
    assert x_count.id == "test.quantum.decorated"
    assert x_count.description == "Repeat X and measure once."
    assert [port.id for port in x_count.ports] == ["qubit", "count"]
    domain = authoring._domain_program(x_count)
    qubit_type = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    assert [port.value_type for port in domain.input_ports] == [
        qubit_type,
        count_type,
    ]
    assert x_count.results[0] is x_count.results["iq_shots"]
    assert x_count.results.iq_shots is x_count.results[0]
    signature = inspect.signature(x_count)
    assert tuple(signature.parameters) == ("qubit", "count", "shots")
    assert signature.parameters["shots"].kind is inspect.Parameter.KEYWORD_ONLY
    assert cast("object", signature.parameters["shots"].default) == 1
    assert cast("object", signature.return_annotation) is authoring.QuantumProgramCall
    assert x_count.__wrapped__.__name__ == "x_count"
    assert isinstance(x_count, authoring.ProgramDefinition)
    with pytest.raises(KeyError):
        _ = x_count.results["missing"]


def test_program_decorator_preserves_signature_order_and_rejects_unused_ports() -> None:
    x = authoring.single_qubit_gate("x")

    @authoring.program
    def ordered(
        qubit: authoring.Qubit,
        first: int,
        second: int,
    ) -> authoring.QuantumFragment:
        return authoring.sequence(
            authoring.repeat(x(qubit), second),
            authoring.repeat(x(qubit), first),
            authoring.measure(qubit, result="iq"),
        )

    assert [port.id for port in ordered.ports] == ["qubit", "first", "second"]

    with pytest.raises(ValueError, match="unused scalar ports: 'unused'"):

        @authoring.program
        def invalid(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
            unused: int,
        ) -> authoring.QuantumFragment:
            return authoring.measure(qubit, result="iq")


def test_program_decorator_rejects_mismatched_and_reserved_ports() -> None:
    x = authoring.single_qubit_gate("x")

    with pytest.raises(TypeError, match="Python annotation is incompatible"):

        @authoring.program
        def mismatched(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
            count: Annotated[str, GateParameterKind.INTEGER],
        ) -> authoring.QuantumFragment:
            return authoring.sequence(
                authoring.repeat(x(qubit), cast("int", cast("object", count))),
                authoring.measure(qubit, result="iq"),
            )

    with pytest.raises(ValueError, match="reserved port ids: 'shots'"):

        @authoring.program
        def reserved(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
            shots: int,
        ) -> authoring.QuantumFragment:
            return authoring.sequence(
                authoring.repeat(x(qubit), shots),
                authoring.measure(qubit, result="iq"),
            )


def test_program_result_named_values_uses_named_access() -> None:
    qubit = authoring.qubit("q0")
    declaration = authoring._close_program(
        "test.quantum.result-values",
        authoring.measure(qubit, result="values"),
    )

    assert declaration.results.values.id == "values"


def test_program_call_owns_domain_effect_shots_and_named_products() -> None:
    x = authoring.single_qubit_gate("x")

    @authoring.program(id="test.quantum.call")
    def x_count(
        qubit: authoring.Qubit,
        count: Annotated[int, GateParameterKind.INTEGER],
    ) -> authoring.QuantumFragment:
        return authoring.sequence(
            authoring.repeat(x(qubit), count),
            authoring.measure(qubit, result="iq_shots"),
        )

    call = assert_type(
        x_count("q0", 2, shots=32),
        authoring.QuantumProgramCall,
    )
    with pytest.raises(TypeError, match="missing a required argument: 'count'"):
        x_count("q0", shots=32)
    module = call.module_invocation.module
    assert call.module_invocation.instance_id == "call"
    assert [port.id for port in module.input_ports] == [
        "qubit",
        "count",
        "__shots__",
    ]
    assert len(module.domain_executions) == 1
    assert module.ir.body.acquisitions == ()
    [product] = module.product_declarations
    assert product.id == "iq_shots"
    assert product.dtype == "complex128"
    assert product.unit == "ratio"
    assert len(product.axes) == 1
    assert product.axes[0].kind == "shot"
    assert call.results.iq_shots is call.results["iq_shots"]
    assert call.results.iq_shots.id == "call/iq_shots"

    @sc.template(id="test.quantum.call-template", kind="x_count")
    def experiment() -> sc.ExperimentBody:
        return sc.experiment(call).record_product(call.results.iq_shots)

    invocation = experiment()
    assert invocation.template.record_selections[0].product_id.qualified_name == (
        "call/iq_shots"
    )


def test_repeated_program_calls_require_explicit_instances() -> None:
    q0 = authoring.qubit("q0")
    readout = authoring.measure(q0, result="iq")
    declaration = authoring._close_program("test.quantum.repeated", readout)

    with pytest.raises(ValueError, match="duplicate instance ids"):
        sc.experiment(declaration(shots=8), declaration(shots=8))

    left = declaration.call("left", shots=8)
    right = declaration.call("right", shots=8)
    body = sc.experiment(left, right)
    assert [item.instance_id for item in body.module.invocations] == ["left", "right"]
    assert left.results.iq.id == "left/iq"
    assert right.results.iq.id == "right/iq"


def test_parent_transform_consumes_program_call_result() -> None:
    q0 = authoring.qubit("q0")
    declaration = authoring._close_program(
        "test.quantum.discriminate",
        authoring.measure(q0, result="iq_shots"),
    )
    call = declaration(shots=16)
    body = sc.module_body().use(call).product("probability_0", "probability_1")
    transform = binary_iq_probability_transform(
        "discriminate",
        iq_shots=call.results.iq_shots,
        probability_0=body.products.probability_0,
        probability_1=body.products.probability_1,
        discriminator=BinaryIqDiscriminator(
            state_0_centroid=IqCentroid(real=-1, imag=0),
            state_1_centroid=IqCentroid(real=1, imag=0),
        ),
    )

    @sc.module
    def discriminate():
        return body.measurement_transforms(transform)

    assert len(discriminate.ir.body.instances) == 1
    [lowered] = discriminate.ir.body.measurement_transforms
    assert lowered.input_bindings[0][1].qualified_name == "discriminate/iq_shots"
    assert {product.qualified_id for product in discriminate.ir.interface.products} == {
        "discriminate/iq_shots",
        "probability_0",
        "probability_1",
    }


def test_program_call_rejects_unmodeled_raw_trace_shape() -> None:
    q0 = authoring.qubit("q0")
    raw = authoring.measure(
        q0,
        result="trace",
        acquisition_kind=AcquisitionKind.RAW_TRACE,
    )
    declaration = authoring._close_program("test.quantum.raw", raw)

    with pytest.raises(NotImplementedError, match="integrated-IQ"):
        declaration(shots=8)
