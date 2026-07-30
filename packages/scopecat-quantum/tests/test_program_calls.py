from __future__ import annotations

import inspect
from pathlib import Path
from typing import Annotated, assert_type, cast

import pytest
import scopecat as sc
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment

from scopecat_quantum import authoring
from scopecat_quantum.gates import GateCall, GateParameterKind
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)

_REPO_ROOT = Path(__file__).parents[3]


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
    assert tuple(signature.parameters) == ("qubit", "count")
    assert cast("object", signature.return_annotation) is authoring.QuantumProgramCall
    assert x_count.__wrapped__.__name__ == "x_count"
    assert isinstance(x_count, authoring.ProgramDefinition)


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


def test_definition_signatures_own_every_live_port() -> None:
    x = authoring.single_qubit_gate("x")
    external_count = authoring.scalar_input(
        "external_count",
        GateParameterKind.INTEGER,
    )

    with pytest.raises(ValueError, match="captures undeclared scalar ports"):

        @authoring.program
        def captured_input(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
        ) -> authoring.QuantumFragment:
            return authoring.sequence(
                authoring.repeat(x(qubit), external_count),
                authoring.measure(qubit, result="iq"),
            )

    fixed = authoring.qubit("fixed")
    with pytest.raises(ValueError, match="captures undeclared formal elements"):

        @authoring.program
        def captured_element(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
        ) -> authoring.QuantumFragment:
            return authoring.sequence(
                x(qubit),
                x(fixed),
                authoring.measure(qubit, result="iq"),
            )

    external_amplitude = authoring.input(
        "external_amplitude",
        sc.ScalarType(sc.QuantityType(unit="arb")),
    )
    with pytest.raises(ValueError, match="captures undeclared scalar ports"):

        @authoring.pulse_template
        def captured_pulse_input(  # pyright: ignore[reportUnusedFunction]
            qubit: authoring.Qubit,
        ) -> authoring.QuantumFragment:
            return authoring.play(
                authoring.drive(qubit),
                authoring.constant(
                    duration=sc.Quantity(8, "ns"),
                    amplitude=external_amplitude,
                ),
            )


def test_fragment_decorator_expands_from_point_bound_inputs() -> None:
    x = authoring.single_qubit_gate("x")
    y = authoring.single_qubit_gate("y")
    elaborations: list[tuple[int, int]] = []

    @authoring.fragment(id="test.quantum.seeded-sequence")
    def seeded_sequence(
        qubit: authoring.Qubit,
        length: Annotated[int, sc.IntType(minimum=1)],
        seed: Annotated[int, sc.IntType(minimum=0)],
    ) -> authoring.QuantumFragment:
        elaborations.append((length, seed))
        return authoring.sequence(
            *(
                x(qubit) if (seed + index) % 2 == 0 else y(qubit)
                for index in range(length)
            )
        )

    @authoring.program(id="test.quantum.seeded-program")
    def seeded_program(
        qubit: authoring.Qubit,
        length: Annotated[int, sc.IntType(minimum=1)],
        seed: Annotated[int, sc.IntType(minimum=0)],
    ) -> authoring.QuantumFragment:
        return authoring.sequence(
            seeded_sequence(qubit, length, seed),
            authoring.measure(qubit, result="iq"),
        )

    assert elaborations == []
    assert [port.id for port in seeded_program.ports] == ["qubit", "length", "seed"]
    assert inspect.signature(seeded_sequence) == inspect.signature(
        seeded_sequence.__wrapped__
    )

    bound = authoring.bind(
        seeded_program,
        {"qubit": "q0", "length": 3, "seed": 1},
    )

    assert elaborations == [(3, 1)]
    calls = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, GateCall)
    )
    assert [call.gate_id.value for call in calls] == ["y", "x", "y"]
    assert [definition.id.value for definition in bound.gate_definitions] == ["x", "y"]
    assert all(
        "fragment[test.quantum.seeded-sequence]" in call.id.value for call in calls
    )


def test_fragment_expansion_rejects_results_and_cycles() -> None:
    @authoring.fragment(id="test.quantum.hidden-result")
    def hidden_result(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.measure(qubit, result="hidden")

    @authoring.program
    def invalid_result(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.sequence(
            hidden_result(qubit),
            authoring.measure(qubit, result="visible"),
        )

    with pytest.raises(ValueError, match="cannot produce results"):
        authoring.bind(invalid_result, {"qubit": "q0"})

    @authoring.fragment(id="test.quantum.recursive")
    def recursive(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return recursive(qubit)

    @authoring.program
    def invalid_cycle(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.sequence(
            recursive(qubit),
            authoring.measure(qubit, result="iq"),
        )

    with pytest.raises(authoring.ProgramBindingError, match="expansion cycle"):
        authoring.bind(invalid_cycle, {"qubit": "q0"})


def test_program_decorator_rejects_mismatched_ports() -> None:
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

    default_call = x_count("q0", 2)
    call = assert_type(
        default_call.with_shots(32),
        authoring.QuantumProgramCall,
    )
    repeated_call = x_count.call("second", "q0", 3)

    assert default_call.module_invocation.module is call.module_invocation.module
    assert repeated_call.module_invocation.module is call.module_invocation.module
    assert call.shots == 32
    assert call.arguments == (("qubit", "q0"), ("count", 2))
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
    assert invocation.definition.record_selections[0].product_id.qualified_name == (
        "call/iq_shots"
    )


def test_program_results_share_one_explicit_shot_dimension() -> None:
    @authoring.program(id="test.quantum.multi-result")
    def declaration(
        first: authoring.Qubit,
        second: authoring.Qubit,
    ) -> authoring.QuantumFragment:
        return authoring.parallel(
            authoring.measure(first, result="first_iq"),
            authoring.measure(second, result="second_iq"),
        )

    call = declaration("q0", "q1").with_shots(16)

    @sc.template(id="test.quantum.multi-result", kind="quantum")
    def experiment() -> sc.ExperimentBody:
        return sc.experiment(call).record_product(
            call.results.first_iq,
            call.results.second_iq,
        )

    linked = resolve_compiled_invocation(
        compile_invocation(experiment()),
        environment=build_config_environment(
            load_config_snapshot_document(
                _REPO_ROOT
                / "fixtures"
                / "core"
                / "simple_scan"
                / "config-snapshot.json"
            )
        ),
    )

    dimensions = [
        product.axes[0].dimension_id for product in linked.program.product_defs
    ]
    assert len(set(dimensions)) == 1
    assert all(
        product.axes[0].dimension_label == "shot"
        for product in linked.program.product_defs
    )


def test_program_call_binds_compiler_collection_outside_program_arguments() -> None:
    @authoring.program(id="test.quantum.compiler-collection")
    def declaration(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.measure(qubit, result="iq")

    table_type = sc.TableType(
        columns=(
            sc.TableColumn("qubit", sc.ScalarType(sc.StringType())),
            sc.TableColumn("gain", sc.ScalarType(sc.FloatType())),
        ),
        primary_key=("qubit",),
    )
    qubits = sc.parameter("qubits", table_type)
    call = declaration("q0").with_compiler_inputs(qubits=qubits)
    with_shots = call.with_shots(16)

    assert call.arguments == (("qubit", "q0"),)
    assert call.compiler_arguments == (("qubits", qubits),)
    assert with_shots.compiler_arguments == call.compiler_arguments
    assert with_shots.module_invocation.module is call.module_invocation.module
    assert [port.id for port in call.module_invocation.module.input_ports] == [
        "qubit",
        "qubits",
        "__shots__",
    ]
    [execution] = call.module_invocation.module.domain_executions
    assert tuple(port.id for port in execution.program.input_ports) == ("qubit",)
    assert tuple(port.id for port in execution.program.compiler_input_ports) == (
        "qubits",
    )


def test_repeated_program_calls_require_explicit_instances() -> None:
    @authoring.program(id="test.quantum.repeated")
    def declaration(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.measure(qubit, result="iq")

    with pytest.raises(ValueError, match="duplicate module instance ids"):
        sc.experiment(
            declaration("q0").with_shots(8),
            declaration("q0").with_shots(8),
        ).module.build(id="test.quantum.repeated-defaults")

    left = declaration.call("left", "q0").with_shots(8)
    right = declaration.call("right", "q0").with_shots(8)
    body = sc.experiment(left, right)
    assert [
        item.instance_id
        for item in body.module.procedure
        if isinstance(item, sc.ModuleInvocation)
    ] == [
        "left",
        "right",
    ]
    assert left.results.iq.id == "left/iq"
    assert right.results.iq.id == "right/iq"


def test_parent_postprocessor_consumes_program_call_result() -> None:
    @authoring.program(id="test.quantum.discriminate")
    def declaration(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.measure(qubit, result="iq_shots")

    call = declaration("q0").with_shots(16)
    body = sc.procedure().use(call).product("probability_0", "probability_1")
    postprocessor = binary_iq_probability_postprocessor(
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
        return body.measurement_postprocessors(postprocessor)

    assert len(discriminate.ir.body.child_instances) == 1
    [lowered] = discriminate.ir.body.measurement_postprocessors
    assert lowered.input_binding.qualified_name == "discriminate/iq_shots"
    assert {product.qualified_id for product in discriminate.ir.products} == {
        "discriminate/iq_shots",
        "probability_0",
        "probability_1",
    }
