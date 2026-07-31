# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.compiler.frontend.elaboration import (
    LogicalProgram,
    compose_module,
)
from scopecat.compiler.frontend.logical_verification import verify_logical_program
from scopecat.compiler.frontend.program_lowering import link_verified_assembly
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
)
from scopecat.compiler.frontend.scan_lowering import lower_scans_point_domain
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    PlanExpressionSource,
    ValueUse,
)
from scopecat.config.environment import build_config_environment
from scopecat.graph.relations.model import (
    InputScalarExpr,
    LiteralScalarExpr,
    as_scalar_expr,
    input_ref,
    param,
)
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.program.scans import (
    AxisSpec,
    scan_parameter_contracts,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
    internal_value_ref_from_expression,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.program.values import compute as program_compute
from scopecat.program.values import input as program_input
from scopecat.records.config import (
    RoutingEndpointBinding,
    RoutingGraph,
)
from scopecat.records.parameter import (
    ParameterDefinition,
    TableParameterValue,
)
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    link_invocation,
    load_config,
    simple_template,
)
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_properties,
    measurement_projection_contract,
)
from tests.testkit.relation_plans import evaluate_scalar


def _identity_value(*, value: object) -> object:
    return value


def _collect_values(**values: object) -> dict[str, object]:
    return values


def _table_definition(
    *,
    id: str,
    primary_key: list[str],
    columns: list[sc.TableColumn],
) -> ParameterDefinition:
    return ParameterDefinition(
        id=id,
        value_type=sc.TableType(
            columns=tuple(columns),
            primary_key=tuple(primary_key),
        ),
    )


_QUANTITY_VALUE = authoring.ScalarType(authoring.QuantityType())

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1")
_SET_FREQUENCY_VALUE = _SET_FREQUENCY.property("frequency")
_SET_FREQUENCY_SIGNAL = _SET_FREQUENCY.acquisition("sample").result("signal")
_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_VALUE = _SCALAR_SIGNAL.acquisition("sample").result("signal")
_SCALAR_IQ_VALUE = _SCALAR_SIGNAL.acquisition("sample").result("iq")
_PLAY_PULSE_PROGRAM = InterfaceRef("test.play_pulse_program/v1")
_PLAY_PULSE = _PLAY_PULSE_PROGRAM.operation("play")
_PLAY_PULSE_PROGRAM_ARGUMENT = _PLAY_PULSE.argument("program")
_ACQUIRE_SIGNAL = InterfaceRef("test.acquire_signal/v1")
_SET_OFFSET = InterfaceRef("test.set_offset/v1")
_SET_OFFSET_VALUE = _SET_OFFSET.property("offset")
_SET_GAIN = InterfaceRef("test.set_gain/v1")
_SET_GAIN_VALUE = _SET_GAIN.property("gain")
_DRIVE_FREQUENCY = InterfaceRef("test.drive_frequency/v1")
_DRIVE_FREQUENCY_VALUE = _DRIVE_FREQUENCY.property("value")

type _EntityInput = Annotated[
    sc.Input[EntityRef | str],
    sc.EntityType(),
]
type _LogicalDeviceInput = Annotated[
    sc.Input[EntityRef | str],
    sc.EntityType(entity_kind="logical_device"),
]
type _QuantityInput = Annotated[
    sc.Input[Quantity],
    sc.QuantityType(),
]
type _FloatInput = Annotated[sc.Input[float], sc.FloatType()]


def test_module_invoke_rejects_argument_from_another_operation() -> None:
    unrelated = _PLAY_PULSE_PROGRAM.operation("preview").argument("program")

    with pytest.raises(
        ValueError,
        match="arguments must belong to the selected operation",
    ):

        @sc.module(id="test.invoke.argument-target")
        def module(context: sc.ModuleContext) -> None:
            drive = context.resource("drive", requires=(_PLAY_PULSE_PROGRAM,))
            context.invoke(
                "play-program",
                resource=drive,
                operation=_PLAY_PULSE,
                arguments={unrelated: True},
            )


def _around_parameter_axis(
    parameter_id: str = "drive_frequency",
    *,
    points: int = 5,
) -> AxisSpec:
    point_type = authoring.ScalarType(authoring.QuantityType(unit="GHz"))
    return cast(
        "AxisSpec",
        sc.axis(
            sc.coordinate(parameter_id, point_type),
            center=sc.parameter(parameter_id, _QUANTITY_VALUE),
            span=Quantity(value=200.0, unit="MHz"),
            points=points,
        ),
    )


def test_module_invocation_resolves_roles_scans_and_bindings() -> None:
    template = simple_template()
    assert template.definition.metadata == {"assembled_by": "template"}

    resolved = link_invocation(
        template.bind(subject="q0"),
        config_profile=load_config(),
    )

    experiment = resolved.program
    assert experiment.id == "test.simple_scan"
    assert experiment.kind == "simple_scan"
    preview = materialized_effects_contract(
        experiment, resolved.environment.parameters, config=load_config()
    )
    projection = measurement_projection_contract(
        experiment, resolved.environment.parameters, config=load_config()
    )

    assert projection.coordinate_ids == ("drive_frequency",)
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert [record.id for record in experiment.record_uses] == ["signal"]
    _, state, target = materialized_state_properties(preview)[0]
    assert state.instrument_id == "source-0"
    assert target.interface_id == "test.set_frequency/v1"
    assert target.property_id == "frequency"
    assert target.value.root == Quantity(value=4.9, unit="GHz")


def test_template_selects_module_products_as_records() -> None:
    @sc.module(id="test.product_module")
    def module(
        context: sc.ModuleContext,
        subject: _EntityInput,
    ) -> None:
        del subject
        source = context.resource(
            "source",
            requires=(_SET_FREQUENCY, _SCALAR_SIGNAL),
        )
        signal = context.product("signal", unit="ratio")
        context.acquire(
            "read-signal",
            resource=source,
            results={_SCALAR_SIGNAL_VALUE: signal},
        )

    scan = sc.axis(DRIVE_FREQUENCY_POINT, [4.9, 5.0, 5.1], unit="GHz")

    @sc.template(id="test.product_unselected", kind="product_test")
    def without_selection(
        experiment: sc.ExperimentContext,
        subject: _EntityInput,
    ) -> None:
        experiment.run(module(subject=subject))
        experiment.scan(scan)

    @sc.template(id="test.product_selected", kind="product_test")
    def with_selection(
        experiment: sc.ExperimentContext,
        subject: _EntityInput,
    ) -> None:
        call = experiment.run(module(subject=subject))
        experiment.scan(scan)
        experiment.record(call.products.signal)

    unselected = link_invocation(
        without_selection(subject="q0"),
        config_profile=load_config(),
    )
    selected = link_invocation(
        with_selection(subject="q0"),
        config_profile=load_config(),
    )

    assert unselected.program.record_uses == ()
    assert [
        product.id.qualified_name for product in unselected.program.product_defs
    ] == ["product_module/signal"]
    assert [record.id for record in selected.program.record_uses] == ["signal"]
    assert selected.program.record_uses[0].metadata == {}
    assert (
        selected.program.product_uses[0].product_id.qualified_name
        == "product_module/signal"
    )


def test_compute_inputs_keep_template_input_provenance() -> None:
    def build_program(
        *,
        qubit: object,
        length: object,
        frequency: object,
    ) -> dict[str, object]:
        return {
            "qubit": qubit,
            "length": length,
            "frequency": frequency,
        }

    @sc.module(id="test.compute_provenance")
    def module(
        context: sc.ModuleContext,
        qubit: _EntityInput,
        pulse_length: _QuantityInput,
        frequency: _QuantityInput,
    ) -> None:
        qubit_ref = sc.input_ref(qubit)
        build = context.compute(
            "build-program",
            fn=build_program,
            output_type=authoring.ScalarType(authoring.PayloadType("pulse")),
            inputs={
                "qubit": qubit_ref,
                "length": pulse_length,
                "frequency": frequency,
            },
        )
        drive = context.resource("drive", requires=(_PLAY_PULSE_PROGRAM,))
        context.invoke(
            "play-program",
            resource=drive,
            operation=_PLAY_PULSE,
            arguments={_PLAY_PULSE_PROGRAM_ARGUMENT: build},
        )

    @sc.template(id="test.compute_provenance", kind="compute_provenance")
    def template(
        experiment: sc.ExperimentContext,
        qubit: _EntityInput,
        pulse_length: _QuantityInput,
    ) -> None:
        qubit_ref = sc.input_ref(qubit)
        experiment.run(
            module(
                qubit=qubit,
                pulse_length=pulse_length,
                frequency=sc.parameter_lookup(
                    "sample_qubits",
                    key={"qubit": qubit_ref},
                    column="drive_frequency",
                    value_type=authoring.ScalarType(authoring.QuantityType()),
                ),
            )
        )

    compiled = compile_invocation(
        template(
            qubit="q0",
            pulse_length=Quantity(value=20.0, unit="ns"),
        )
    )
    graph = compiled.program.program.semantic_graph
    operation = next(
        operation
        for operation in graph.operations
        if operation.id.local_id == "build-program"
    )
    definitions = {definition.id: definition for definition in graph.value_defs}
    uses = dict(operation.inputs)

    assert all(isinstance(use, ValueUse) for use in uses.values())
    qubit_source = definitions[uses["qubit"].value_id].source
    length_source = definitions[uses["length"].value_id].source
    frequency_source = definitions[uses["frequency"].value_id].source
    assert isinstance(qubit_source, PlanExpressionSource)
    assert isinstance(length_source, PlanExpressionSource)
    assert isinstance(frequency_source, PlanExpressionSource)
    assert qubit_source.source_inputs == ("qubit",)
    assert length_source.source_inputs == ("pulse_length",)
    assert frequency_source.source_inputs == ("qubit",)
    assert operation.result_type == authoring.ScalarType(authoring.PayloadType("pulse"))


def test_compute_function_signature_must_match_explicit_inputs() -> None:
    output_type = authoring.ScalarType(authoring.StringType())

    with pytest.raises(TypeError, match="does not match declared inputs"):
        program_compute(
            "missing-input",
            fn=_identity_value,
            output_type=output_type,
        )

    with pytest.raises(TypeError, match="must use explicit named parameters"):
        program_compute(
            "variadic-inputs",
            fn=_collect_values,
            inputs={"value": "declared"},
            output_type=output_type,
        )


def test_runtime_entity_scan_feeds_resource_selection_and_parameter_lookup() -> None:
    seed_config = load_config()
    source_0 = seed_config.instrument_registry.instruments[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
        }
    )
    catalog = seed_config.parameter_catalog.model_copy(
        update={
            "definitions": [
                *seed_config.parameter_catalog.definitions,
                _table_definition(
                    id="sample_qubits",
                    primary_key=["qubit"],
                    columns=[
                        sc.TableColumn(
                            id="qubit",
                            value_type=sc.ScalarType(
                                sc.EntityType(entity_kind="logical_device")
                            ),
                        ),
                        sc.TableColumn(
                            id="drive_frequency",
                            value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
                        ),
                    ],
                ),
            ]
        }
    )
    parameter_snapshot = seed_config.parameter_snapshot.model_copy(
        update={
            "values": [
                *seed_config.parameter_snapshot.values,
                TableParameterValue(
                    id="sample_qubits",
                    rows=[
                        {
                            "qubit": "q0",
                            "drive_frequency": Quantity(value=5.0, unit="GHz"),
                        },
                        {
                            "qubit": "q1",
                            "drive_frequency": Quantity(value=5.1, unit="GHz"),
                        },
                    ],
                ),
            ]
        }
    )
    system = seed_config.system.model_copy(
        update={
            "topology": topology,
            "parameter_catalog": catalog,
            "instrument_registry": seed_config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source_0,
                        source_0.model_copy(
                            update={
                                "id": "source-1",
                                "exclusivity_key": "source-1",
                            }
                        ),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="source-0",
                        interface_id="test.set_frequency/v1",
                        entity_id="q0",
                        channel_id="drive-q0",
                    ),
                    RoutingEndpointBinding(
                        instrument_id="source-1",
                        interface_id="test.set_frequency/v1",
                        entity_id="q1",
                        channel_id="drive-q1",
                    ),
                ],
            ),
        }
    )
    config = seed_config.model_copy(
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )
    qubit = sc.coordinate(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )

    @sc.module(id="test.runtime_entity_scan")
    def module(
        context: sc.ModuleContext,
        qubit_input: _LogicalDeviceInput,
        drive_frequency: _QuantityInput,
    ) -> None:
        qubit_ref = sc.input_ref(qubit_input)
        drive = context.resource(
            "drive",
            requires=(_SET_FREQUENCY,),
            for_entities=(qubit_ref,),
        )
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )
        signal = context.product("signal", unit="ratio")
        context.acquire(
            "read-signal",
            resource=drive,
            results={_SET_FREQUENCY_SIGNAL: signal},
        )

    @sc.template(id="test.runtime_entity_scan", kind="runtime_entity_scan")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(
            module(
                qubit_input=qubit,
                drive_frequency=authoring.parameter_lookup(
                    "sample_qubits",
                    key={"qubit": qubit},
                    column="drive_frequency",
                    value_type=authoring.ScalarType(authoring.QuantityType(unit="GHz")),
                ),
            )
        )
        experiment.record(call.products.signal)

    resolved = link_invocation(
        template.bind().scan(
            sc.axis(
                qubit,
                ["q0", "q1"],
            )
        ),
        config_profile=config,
    )
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )

    assert [point.coordinates["qubit"] for point in preview.points] == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]
    assert [
        (point_index, state.instrument_id, target.value.root)
        for point_index, state, target in materialized_state_properties(preview)
    ] == [
        (0, "source-0", Quantity(value=5.0, unit="GHz")),
        (1, "source-1", Quantity(value=5.1, unit="GHz")),
    ]


def test_bound_entity_input_can_center_a_default_parameter_scan() -> None:
    seed_config = load_config()
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
        }
    )
    catalog = seed_config.parameter_catalog.model_copy(
        update={
            "definitions": [
                *seed_config.parameter_catalog.definitions,
                _table_definition(
                    id="sample_qubits",
                    primary_key=["qubit"],
                    columns=[
                        sc.TableColumn(
                            id="qubit",
                            value_type=sc.ScalarType(
                                sc.EntityType(entity_kind="logical_device")
                            ),
                        ),
                        sc.TableColumn(
                            id="rabi_length",
                            value_type=sc.ScalarType(sc.QuantityType(unit="ns")),
                        ),
                    ],
                ),
            ]
        }
    )
    parameter_snapshot = seed_config.parameter_snapshot.model_copy(
        update={
            "values": [
                *seed_config.parameter_snapshot.values,
                TableParameterValue(
                    id="sample_qubits",
                    rows=[
                        {
                            "qubit": "q0",
                            "rabi_length": Quantity(value=40.0, unit="ns"),
                        },
                        {
                            "qubit": "q1",
                            "rabi_length": Quantity(value=80.0, unit="ns"),
                        },
                    ],
                ),
            ]
        }
    )
    system = seed_config.system.model_copy(
        update={"topology": topology, "parameter_catalog": catalog},
    )
    config = seed_config.model_copy(
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )

    @sc.module(id="test.runtime_entity_dependent_points")
    def module(
        context: sc.ModuleContext,
        qubit: _LogicalDeviceInput,
    ) -> None:
        del qubit
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        signal = context.product("signal", unit="ratio")
        context.acquire(
            "read-signal",
            resource=source,
            results={_SCALAR_SIGNAL_VALUE: signal},
        )

    drive_length = sc.coordinate("drive_length", _QUANTITY_VALUE)

    @sc.template(
        id="test.runtime_entity_dependent_points",
        kind="runtime_entity_dependent_points",
    )
    def template(
        experiment: sc.ExperimentContext,
        qubit: _LogicalDeviceInput,
    ) -> None:
        call = experiment.run(module(qubit=qubit))
        experiment.scan(
            sc.axis(
                drive_length,
                center=sc.parameter_lookup(
                    "sample_qubits",
                    key={"qubit": sc.input_ref(qubit)},
                    column="rabi_length",
                    value_type=_QUANTITY_VALUE,
                ),
                span=Quantity(value=20.0, unit="ns"),
                points=3,
            ),
        )
        experiment.record(call.products.signal)

    resolved = link_invocation(template(qubit="q0"), config_profile=config)
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )

    assert [point.coordinates["drive_length"] for point in preview.points] == [
        Quantity(value=30.0, unit="ns"),
        Quantity(value=40.0, unit="ns"),
        Quantity(value=50.0, unit="ns"),
    ]


def test_literal_string_values_define_categorical_product_axis() -> None:
    @sc.module(id="test.categorical_axis")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SCALAR_SIGNAL,))
        iq = context.product(
            "iq",
            dtype="complex128",
            axes=(
                authoring.product_axis(
                    "component",
                    size=("I", "Q"),
                    kind="component",
                ),
                authoring.product_axis(
                    "entity_role",
                    size=2,
                    kind="entity",
                ),
            ),
        )
        context.acquire(
            "read-iq",
            resource=source,
            results={_SCALAR_IQ_VALUE: iq},
        )

    @sc.template(id="test.categorical_axis", kind="categorical_axis")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(module())
        experiment.record(call.products.iq)

    resolved = link_invocation(
        template(),
        config_profile=load_config(),
    )

    axis = resolved.program.product_defs[0].axes[0]
    assert axis.size == 2
    assert axis.metadata == {}
    role_axis = resolved.program.product_defs[0].axes[1]
    assert role_axis.kind == "entity"
    assert role_axis.size == 2
    assert role_axis.metadata == {}


def test_request_projection_explicitly_handles_authoring_semantic_values() -> None:
    projected = project_run_request_inputs(
        {
            "subjects": (
                EntityRef(id="q0", kind="qubit"),
                EntityRef(id="q1", kind="qubit"),
            )
        }
    )

    assert projected == {
        "subjects": [
            {
                "kind": "entity",
                "entity_id": "q0",
                "entity_kind": "qubit",
                "metadata": {},
            },
            {
                "kind": "entity",
                "entity_id": "q1",
                "entity_kind": "qubit",
                "metadata": {},
            },
        ]
    }


def test_request_projection_rejects_transient_typed_and_compiler_values() -> None:
    typed_value = program_input(
        "subject",
        sc.ScalarType(sc.EntityType()),
    )
    transient_values = (
        typed_value,
        input_ref("subject"),
        ComputeResultRef(
            value_id=operation_result_id(
                OperationId(SymbolId(local_id="build-program"))
            )
        ),
    )

    for value in transient_values:
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"value": value})
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"nested": {"value": value}})


def test_link_resolves_config_dependent_assembly_fragments() -> None:
    source = compose_module(
        SIMPLE_MODULE.ir,
        subject="q0",
        drive_frequency=DRIVE_FREQUENCY_POINT,
    )
    axis = _around_parameter_axis()
    assembly = replace(
        source,
        experiment_id="authored-simple-scan",
        kind="simple_scan",
        point_domain=lower_scans_point_domain((axis,)),
        parameter_contracts=scan_parameter_contracts(axis),
    )
    environment = build_config_environment(load_config())
    resolved = link_verified_assembly(verify_logical_program(assembly), environment)

    assert resolved.program.id == "authored-simple-scan"
    assert resolved.environment.config.id == load_config().id
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
    )
    assert materialized_state_properties(preview)[0][1].instrument_id == "source-0"


def test_link_validates_scan_axis_parameter_contracts() -> None:
    axis = _around_parameter_axis("missing_frequency")
    assembly = LogicalProgram(
        experiment_id="missing-parameter-scan",
        kind="simple_scan",
        point_domain=lower_scans_point_domain((axis,)),
        parameter_contracts=scan_parameter_contracts(axis),
    )
    environment = build_config_environment(load_config())
    with pytest.raises(CheckFailed) as caught:
        link_verified_assembly(verify_logical_program(assembly), environment)

    assert caught.value.problems[0].code == "unknown_authoring_parameter"
    assert caught.value.problems[0].location == model_location(
        "parameters",
        "missing_frequency",
    )


def test_module_construction_rejects_duplicate_resource_ids() -> None:
    with pytest.raises(ValueError, match="duplicate module resource ids"):

        @sc.module(id="test.shared_resource.duplicate")
        def duplicate_resources(context: sc.ModuleContext) -> None:
            context.resource("source", requires=(_SET_FREQUENCY,))
            context.resource("source", requires=(_ACQUIRE_SIGNAL,))


def test_elaboration_invocation_literals_bind_local_inputs() -> None:
    @sc.module(id="test.invocation_defaults.child")
    def child(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource("source", requires=(_SET_FREQUENCY,))
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_defaults.parent")
    def parent(context: sc.ModuleContext) -> None:
        context.call(
            child.instantiate(
                "defaults-child",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )

    assembly = compose_module(
        parent.ir,
    )

    assert "drive_frequency" not in assembly.inputs
    assert all(port.id != "drive_frequency" for port in assembly.input_ports)
    assert isinstance(assembly.bindings[0].value, ValueRef)
    first_value = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert isinstance(first_value, LiteralScalarExpr)
    assert first_value.value == Quantity(value=5.0, unit="GHz")


def test_elaboration_invocation_expressions_bind_local_inputs() -> None:
    @sc.module(id="test.invocation_override.child")
    def child(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource("source", requires=(_SET_FREQUENCY,))
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_expression.parent")
    def parent(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        context.call(
            child.instantiate(
                "expression-child",
                drive_frequency=drive_frequency,
            )
        )

    @sc.template(id="test.invocation-expression", kind="expression")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(
            parent(
                drive_frequency=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType()),
                )
            )
        )

    assembly = compile_invocation(template()).program.program

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    assert internal_lower_value_ref(assembly.bindings[0].value) == param(
        "drive_frequency"
    )


def test_elaboration_defers_nested_expression_and_literal_bindings() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())

    @sc.module(id="test.invocation_deferred.child")
    def child(
        context: sc.ModuleContext,
        child_value: _FloatInput,
        unused_parameter: _FloatInput,
        unused_point: _FloatInput,
    ) -> None:
        del unused_parameter, unused_point
        source = context.resource("source", requires=(_SET_OFFSET,))
        context.bind_property(
            source,
            _SET_OFFSET_VALUE,
            value=child_value,
        )

    @sc.module(id="test.invocation_deferred.parent")
    def parent(
        context: sc.ModuleContext,
        parent_value: _FloatInput,
        unused_parameter: _FloatInput,
        unused_point: _FloatInput,
    ) -> None:
        parent_ref = sc.input_ref(parent_value)
        context.call(
            child.instantiate(
                "deferred-child",
                child_value=parent_ref + 0.25,
                unused_parameter=unused_parameter,
                unused_point=unused_point,
            )
        )

    @sc.template(id="test.invocation-deferred", kind="deferred")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(
            parent.instantiate(
                "deferred-parent",
                parent_value=1.5,
                unused_parameter=authoring.parameter(
                    "unused_parameter",
                    value_type,
                ),
                unused_point=authoring.coordinate("unused_point", value_type),
            )
        )

    assembly = compile_invocation(template()).program.program

    assert isinstance(assembly.bindings[0].value, ValueRef)
    expression = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert evaluate_scalar(expression, EvalContext()) == 1.75
    assert internal_value_ref_parameter_contracts(assembly.bindings[0].value) == ()
    assert internal_value_ref_point_dependencies(assembly.bindings[0].value) == ()
    assert assembly.parameter_contracts == ()
    assert assembly.point_dependencies == ()


def test_module_provenance_follows_only_reachable_input_bindings() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())

    @sc.module(id="test.reachable-input-provenance")
    def module(
        context: sc.ModuleContext,
        used_parameter: _FloatInput,
        unused_parameter: _FloatInput,
        used_point: _FloatInput,
        unused_point: _FloatInput,
    ) -> None:
        del unused_parameter, unused_point
        source = context.resource(
            "source",
            requires=(_SET_OFFSET, _SET_GAIN),
        )
        context.bind_property(
            source,
            _SET_OFFSET_VALUE,
            value=used_parameter,
        )
        context.bind_property(
            source,
            _SET_GAIN_VALUE,
            value=used_point,
        )

    used_parameter = authoring.parameter("reachable_parameter", value_type)
    unused_parameter = authoring.parameter("phantom_parameter", value_type)
    used_point = authoring.coordinate("reachable_point", value_type)
    unused_point = authoring.coordinate("phantom_point", value_type)

    assembly = compose_module(
        module.ir,
        used_parameter=used_parameter,
        unused_parameter=unused_parameter,
        used_point=used_point,
        unused_point=unused_point,
    )

    assert assembly.parameter_contracts == internal_value_ref_parameter_contracts(
        used_parameter
    )
    assert assembly.point_dependencies == internal_value_ref_point_dependencies(
        used_point
    )


def test_scalar_input_binding_preserves_parent_same_named_input() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    child_value = program_input("value", value_type)
    parent_value = program_input("value", value_type)

    bound = internal_bind_value_ref_inputs(
        child_value + 1.0,
        {"value": parent_value + 1.0},
    )

    assert evaluate_scalar(
        internal_lower_scalar_value_ref(bound),
        EvalContext(inputs={"value": 2.0}),
        bindings=RelationTypeBindings(inputs={"value": value_type}),
    ) == pytest.approx(4.0)


def test_expression_input_binding_does_not_capture_sibling_child_inputs() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    child_value = internal_value_ref_from_expression(input_ref("a"), value_type)
    parent_b = program_input("b", value_type)
    child_b = internal_value_ref_from_expression(as_scalar_expr(10.0), value_type)

    bound = internal_bind_value_ref_inputs(
        child_value,
        {"a": parent_b + 1.0, "b": child_b},
    )

    assert evaluate_scalar(
        internal_lower_scalar_value_ref(bound),
        EvalContext(inputs={"b": 2.0}),
        bindings=RelationTypeBindings(inputs={"b": value_type}),
    ) == pytest.approx(3.0)


def test_elaboration_invocation_input_refs_bind_to_parent_inputs() -> None:
    @sc.module(id="test.invocation_parent_input.child")
    def child(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource("source", requires=(_SET_FREQUENCY,))
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_parent_input.parent")
    def parent(
        context: sc.ModuleContext,
        outer_frequency: _QuantityInput,
    ) -> None:
        context.call(
            child.instantiate(
                "parent-input-child",
                drive_frequency=outer_frequency,
            )
        )

    assembly = compose_module(
        parent.ir, outer_frequency=Quantity(value=5.2, unit="GHz")
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    localized = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert isinstance(localized, InputScalarExpr)
    assert localized.name == "outer_frequency"


def test_elaboration_does_not_merge_sibling_invocation_inputs() -> None:
    @sc.module(id="test.invocation_sibling.first")
    def first(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource("source", requires=(_SET_FREQUENCY,))
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_sibling.second")
    def second(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        detector = context.resource("detector", requires=(_SET_FREQUENCY,))
        context.bind_property(
            detector,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_sibling.parent")
    def module(context: sc.ModuleContext) -> None:
        context.call(
            first.instantiate(
                "first",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )
        context.call(
            second.instantiate(
                "second",
                drive_frequency=Quantity(value=5.1, unit="GHz"),
            )
        )

    assembly = compose_module(
        module.ir,
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    assert isinstance(assembly.bindings[1].value, ValueRef)
    first_value = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    second_value = internal_lower_scalar_value_ref(assembly.bindings[1].value)
    assert isinstance(first_value, LiteralScalarExpr)
    assert isinstance(second_value, LiteralScalarExpr)
    assert first_value.value == Quantity(value=5.0, unit="GHz")
    assert second_value.value == Quantity(value=5.1, unit="GHz")


def test_elaboration_localizes_invocation_entity_inputs() -> None:
    @sc.module(id="test.invocation_entity.child")
    def child(
        context: sc.ModuleContext,
        qubit: _EntityInput,
        drive_frequency: _QuantityInput,
    ) -> None:
        drive = context.resource(
            "drive",
            requires=(_SET_FREQUENCY,),
            for_entities=(sc.input_ref(qubit),),
        )
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.module(id="test.invocation_entity.parent")
    def parent(context: sc.ModuleContext) -> None:
        context.call(
            child.instantiate(
                "entity-child",
                qubit="q0",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )

    assembly = compose_module(
        parent.ir,
    )

    assert "qubit" not in assembly.inputs
    assert "qubit" not in assembly.entity_inputs
    assert all(port.id != "qubit" for port in assembly.input_ports)
    localized_entity = assembly.resource_ports[0].selector.entity_inputs[0]
    assert isinstance(localized_entity, ValueRef)
    assert localized_entity.value_type == authoring.ScalarType(authoring.EntityType())
    lowered_entity = internal_lower_scalar_value_ref(localized_entity)
    assert isinstance(lowered_entity, LiteralScalarExpr)
    assert lowered_entity.value == EntityRef(id="q0")


def test_template_invocation_runs_composed_modules_directly() -> None:
    @sc.module(id="test.scripted_module_prelude")
    def prelude(context: sc.ModuleContext) -> None:
        del context

    @sc.module(id="test.scripted_module_scan")
    def scan(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource(
            "source",
            requires=(_SET_FREQUENCY, _SCALAR_SIGNAL),
        )
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )
        signal = context.product("signal", unit="ratio")
        context.acquire(
            "read-products",
            resource=source,
            results={_SCALAR_SIGNAL_VALUE: signal},
        )

    @sc.template(id="test.scripted_scan", kind="simple_scan")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(prelude())
        call = experiment.run(scan(DRIVE_FREQUENCY_POINT))
        experiment.record(call.products.signal)

    resolved = link_invocation(
        template().scan(
            sc.axis(
                DRIVE_FREQUENCY_POINT,
                center=sc.parameter("drive_frequency", _QUANTITY_VALUE),
                span=Quantity(value=200.0, unit="MHz"),
                points=5,
            )
        ),
        config_profile=load_config(),
    )
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
    )

    assert resolved.program.id == "test.scripted_scan"
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.1, unit="GHz"
    )


def test_product_declaration_uses_axes() -> None:
    @sc.module(id="test.record_axes")
    def module(
        context: sc.ModuleContext,
        drive_frequency: _QuantityInput,
    ) -> None:
        source = context.resource(
            "source",
            requires=(_SET_FREQUENCY, _SCALAR_SIGNAL),
        )
        context.bind_property(
            source,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )
        signal = context.product(
            "signal",
            unit="ratio",
            axes=(
                authoring.shot_axis(2),
                authoring.product_axis("repetition", size=3, kind="repetition"),
            ),
        )
        context.acquire(
            "read-products",
            resource=source,
            results={_SCALAR_SIGNAL_VALUE: signal},
        )

    @sc.template(id="test.record_axes", kind="simple_scan")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(module(DRIVE_FREQUENCY_POINT))
        experiment.record(call.products.signal)

    resolved = link_invocation(
        template().scan(
            sc.axis(
                DRIVE_FREQUENCY_POINT,
                center=sc.parameter("drive_frequency", _QUANTITY_VALUE),
                span=Quantity(value=200.0, unit="MHz"),
                points=5,
            )
        ),
        config_profile=load_config(),
    )

    assert len(resolved.program.record_uses) == 1
    product = resolved.program.product_defs[0]
    assert product.id.local_id == "signal"
    assert [axis.id for axis in product.axes] == ["shot", "repetition"]
    assert [axis.size for axis in product.axes] == [2, 3]


def test_resource_port_can_select_by_fixed_entity_input() -> None:
    seed_config = load_config()
    source_0 = seed_config.instrument_registry.instruments[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
        }
    )
    system = seed_config.system.model_copy(
        update={
            "topology": topology,
            "instrument_registry": seed_config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source_0,
                        source_0.model_copy(
                            update={
                                "id": "source-1",
                                "exclusivity_key": "source-1",
                            }
                        ),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="source-0",
                        interface_id="test.set_frequency/v1",
                        entity_id="q0",
                        channel_id="drive-q0",
                    ),
                    RoutingEndpointBinding(
                        instrument_id="source-1",
                        interface_id="test.set_frequency/v1",
                        entity_id="q1",
                        channel_id="drive-q1",
                    ),
                ],
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})

    @sc.module(id="test.entity_selected_resource")
    def module(
        context: sc.ModuleContext,
        qubit: _EntityInput,
        drive_frequency: _QuantityInput,
    ) -> None:
        drive = context.resource(
            "drive",
            requires=(_SET_FREQUENCY,),
            for_entities=(sc.input_ref(qubit),),
        )
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE,
            value=drive_frequency,
        )

    @sc.template(
        id="test.entity_selected_resource",
        kind="entity_selected_resource",
    )
    def template(
        experiment: sc.ExperimentContext,
        qubit: _EntityInput,
    ) -> None:
        experiment.run(
            module(
                qubit=qubit,
                drive_frequency=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType(unit="GHz")),
                ),
            )
        )

    resolved = link_invocation(
        template(qubit="q1"),
        config_profile=config,
    )

    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )
    assert materialized_state_properties(preview)[0][1].instrument_id == "source-1"


def test_explicit_config_links_experiment() -> None:
    selected_instrument = "spare-awg"
    config = config_with_physical_resources(
        {selected_instrument: ("test.drive_frequency/v1",)}
    )

    @sc.module(id="test.explicit-config-source")
    def module(context: sc.ModuleContext) -> None:
        drive = context.resource("drive", requires=(_DRIVE_FREQUENCY,))
        context.bind_property(
            drive,
            _DRIVE_FREQUENCY_VALUE,
            value=Quantity(value=5.0, unit="GHz"),
        )

    @sc.template(id="test.explicit-config-source", kind="config-source")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(module())

    resolved = link_invocation(template(), config_profile=config)
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )

    [(_point_index, operation, _target)] = materialized_state_properties(preview)
    assert operation.instrument_id == selected_instrument
    assert resolved.environment.config is config
