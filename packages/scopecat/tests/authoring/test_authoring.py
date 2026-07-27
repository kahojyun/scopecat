from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.authoring import ExperimentModule
from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    bind_field,
    requires,
    resource_port,
)
from scopecat.authoring._intents import ModuleInputPort
from scopecat.authoring._module_ir import (
    ModuleAcquireEffect,
    ModuleAcquireProduct,
    ModuleBindingEffect,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
    ProductRef,
)
from scopecat.authoring._scan_intents import (
    AxisSpec,
    scan_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
    internal_value_ref_from_expression,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.compiler.frontend.assembly_linking import bind_verified_assembly
from scopecat.compiler.frontend.assembly_verification import verify_assembly
from scopecat.compiler.frontend.elaboration import (
    SemanticExperimentIR,
    elaborate_module,
)
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
)
from scopecat.compiler.frontend.scan_lowering import (
    lower_scans_point_domain,
    project_scan_record,
)
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    PlanExpressionSource,
    ValueUse,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import CollectOperation
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
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.points import RunPoint
from scopecat.records.config import (
    RoutingEndpointBinding,
    RoutingGraph,
)
from scopecat.records.parameter import (
    ParameterDefinition,
    TableParameterValue,
)
from tests.testkit.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    link_invocation,
    load_config,
    simple_template,
    template_fixture,
)
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_fields,
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


def _module_fixture(
    *,
    id: str,
    entity_inputs: Sequence[str] = (),
    resources: Sequence[ResourcePort] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    products: Sequence[ModuleProductDecl] = (),
) -> ExperimentModule[...]:
    return authoring.ModuleBuilder(
        id=id,
        input_ports=tuple(
            ModuleInputPort(
                id=input_id,
                value_type=authoring.ScalarType(authoring.EntityType()),
            )
            for input_id in entity_inputs
        ),
        resources=tuple(resources),
        procedure=(
            *(ModuleBindingEffect(binding) for binding in bindings),
            *(
                (
                    ModuleAcquireEffect(
                        id="read-products",
                        resource_port_id=logical_resource_port_id("source"),
                        capability_id="scalar_signal",
                        products=tuple(
                            ModuleAcquireProduct(
                                product=ProductRef(
                                    product.product_id,
                                    product.origin,
                                ),
                                provider_key=product.id,
                            )
                            for product in products
                        ),
                    ),
                )
                if products
                else ()
            ),
        ),
        product_declarations=tuple(products),
    ).build()


def _observable_product(
    id: str,
    *,
    unit: str | None = "ratio",
    axes: Sequence[authoring.ProductAxis] = (),
) -> ModuleProductDecl:
    return ModuleProductDecl(
        id=id,
        unit=unit,
        axes=tuple(axes),
    )


def _template_invocation(
    *modules: ExperimentModule[...],
    id: str,
    kind: str,
    inputs: Mapping[str, authoring.RuntimeInput] | None = None,
    metadata: Mapping[str, authoring.MetadataValue] | None = None,
) -> authoring.ExperimentInvocation:
    input_types: dict[str, authoring.ValueType] = {}
    for module in modules:
        for port in module.input_ports:
            existing = input_types.setdefault(port.id, port.value_type)
            if existing != port.value_type:
                raise AssertionError(f"conflicting test module input {port.id!r}")
    root_inputs = {
        input_id: authoring.input(input_id, value_type)
        for input_id, value_type in input_types.items()
    }
    instances = tuple(
        module.instantiate(
            module.id,
            {port.id: root_inputs[port.id] for port in module.input_ports},
        )
        for module in modules
    )
    root_module = (
        authoring.module_body(id=f"{id}.root")
        .inputs(*root_inputs.values())
        .use(*instances)
        .build()
    )
    records: list[authoring.RecordSelection] = []
    for instance in instances:
        for product in instance.products.values():
            records.append(
                authoring.record_product(
                    product,
                    record_id=product.local_id,
                )
            )
    template = template_fixture(
        root_module,
        id=id,
        kind=kind,
        records=records,
        metadata=metadata,
    )
    return template.bind(**dict(inputs or {}))


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
    _, state, field = materialized_state_fields(preview)[0]
    assert state.instrument_id == "source-0"
    assert field.capability_id == "set_frequency"
    assert field.field_path == "frequency"
    assert field.value.root == Quantity(value=4.9, unit="GHz")


def test_template_selects_module_products_as_records() -> None:
    subject = authoring.input(
        "subject",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module_body(id="test.product_module")
        .inputs(subject)
        .resource("source", requires=("set_frequency", "scalar_signal"))
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    scan = sc.axis(DRIVE_FREQUENCY_POINT, [4.9, 5.0, 5.1], unit="GHz")
    without_selection = template_fixture(
        module,
        id="test.product_unselected",
        kind="product_test",
        scans=(scan,),
    )
    with_selection = template_fixture(
        module,
        id="test.product_selected",
        kind="product_test",
        scans=(scan,),
        records=(authoring.record_product(module.products.signal),),
    )

    unselected = link_invocation(
        without_selection.bind(subject="q0"),
        config_profile=load_config(),
    )
    selected = link_invocation(
        with_selection.bind(subject="q0"),
        config_profile=load_config(),
    )

    assert unselected.program.record_uses == ()
    assert [
        product.id.qualified_name for product in unselected.program.product_defs
    ] == ["signal"]
    assert [record.id for record in selected.program.record_uses] == ["signal"]
    assert selected.program.record_uses[0].metadata == {}
    assert selected.program.product_uses[0].product_id.qualified_name == "signal"


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

    qubit = sc.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    pulse_length = sc.input(
        "pulse_length",
        authoring.ScalarType(authoring.QuantityType()),
    )
    build = sc.compute(
        "build-program",
        fn=build_program,
        output_type=authoring.ScalarType(authoring.PayloadType("pulse")),
        inputs={
            "qubit": qubit,
            "length": pulse_length,
            "frequency": sc.parameter_lookup(
                "sample_qubits",
                key={"qubit": qubit},
                column="drive_frequency",
                value_type=authoring.ScalarType(authoring.QuantityType()),
            ),
        },
    )
    module = (
        authoring.module_body(id="test.compute_provenance")
        .inputs(qubit, pulse_length)
        .resource("drive", requires=("play_pulse_program",))
        .computes(build)
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=build.output,
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.compute_provenance",
        kind="compute_provenance",
        defaults={"pulse_length": Quantity(value=20.0, unit="ns")},
    )
    compiled = compile_invocation(template.bind(qubit="q0"))
    graph = compiled.assembly.source.semantic_graph
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
        sc.compute(
            "missing-input",
            fn=_identity_value,
            output_type=output_type,
        )

    with pytest.raises(TypeError, match="must use explicit named parameters"):
        sc.compute(
            "variadic-inputs",
            fn=_collect_values,
            inputs={"value": "declared"},
            output_type=output_type,
        )


def test_template_can_scan_entity_points() -> None:
    qubit = sc.coordinate(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module_body(id="test.entity_scan_module")
        .resource("source", requires=("scalar_signal",))
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.entity_scan",
        kind="entity_scan",
        scans=(
            sc.axis(
                qubit,
                [EntityRef(id="q0", kind="logical_device")],
            ),
        ),
        records=(authoring.record_product(module.products.signal),),
    )

    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
    )
    projection = measurement_projection_contract(
        resolved.program,
        resolved.environment.parameters,
    )

    assert preview.points[0].coordinates["qubit"] == EntityRef(
        id="q0", kind="logical_device"
    )
    schema = projection.schema_for(
        tuple(
            RunPoint(point.logical_id, dict(point.coordinates))
            for point in preview.points
        )
    )
    assert schema is not None
    coordinate = next(
        variable for variable in schema.variables if variable.id == "qubit"
    )
    assert coordinate.dtype == "string"
    assert coordinate.metadata == {"entity_kind": "logical_device"}


def test_entity_scan_captures_an_immutable_durable_snapshot() -> None:
    subject = sc.coordinate(
        "subject",
        sc.ScalarType(sc.EntityType()),
    )
    labels = ["data"]
    entity = EntityRef(id="q0", metadata={"labels": labels})

    scan = sc.axis(subject, [entity])
    labels.append("changed")
    request = project_scan_record(cast("AxisSpec", scan))

    assert request.model_dump(mode="json")["values"] == [
        {
            "kind": "entity",
            "entity_id": "q0",
            "entity_kind": None,
            "metadata": {"labels": ["data"]},
        }
    ]


def test_entity_scan_selects_resource_entities_per_point() -> None:
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
                        source_0.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="source-0",
                        capability="set_frequency",
                        entity_id="q0",
                        channel_id="drive-q0",
                    ),
                    RoutingEndpointBinding(
                        instrument_id="source-1",
                        capability="set_frequency",
                        entity_id="q1",
                        channel_id="drive-q1",
                    ),
                ],
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})
    qubit = sc.coordinate(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module_body(id="test.entity_scan_selection")
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind_field(
            "drive",
            capability="set_frequency",
            field="frequency",
            value=Quantity(value=5.0, unit="GHz"),
        )
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="drive",
            capability="set_frequency",
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.entity_scan_selection",
        kind="entity_scan_selection",
        scans=(
            sc.axis(
                qubit,
                [
                    EntityRef(id="q0", kind="logical_device"),
                    EntityRef(id="q1", kind="logical_device"),
                ],
            ),
        ),
        records=(authoring.record_product(module.products.signal),),
    )

    resolved = link_invocation(
        template.bind(),
        config_profile=config,
    )
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )

    assert [point.ordinal for point in preview.points] == [0, 1]
    assert [
        state.instrument_id for _, state, _ in materialized_state_fields(preview)
    ] == [
        "source-0",
        "source-1",
    ]
    collections = [
        operations_of_type(preview, CollectOperation, point_index=point_index)[0]
        for point_index in range(2)
    ]
    assert [operation.instrument_id for operation in collections] == [
        "source-0",
        "source-1",
    ]
    assert [
        (
            tuple(request.entity_ids),
            tuple(binding.channel_id for binding in request.channel_bindings),
        )
        for operation in collections
        for request in operation.command.requests
    ] == [
        (("q0",), ("drive-q0",)),
        (("q1",), ("drive-q1",)),
    ]


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
                        source_0.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="source-0",
                        capability="set_frequency",
                        entity_id="q0",
                        channel_id="drive-q0",
                    ),
                    RoutingEndpointBinding(
                        instrument_id="source-1",
                        capability="set_frequency",
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
    module = (
        authoring.module_body(id="test.runtime_entity_scan")
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind_field(
            "drive",
            capability="set_frequency",
            field="frequency",
            value=authoring.parameter_lookup(
                "sample_qubits",
                key={"qubit": qubit},
                column="drive_frequency",
                value_type=authoring.ScalarType(authoring.QuantityType(unit="GHz")),
            ),
        )
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="drive",
            capability="set_frequency",
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.runtime_entity_scan",
        kind="runtime_entity_scan",
        records=(authoring.record_product(module.products.signal),),
    )

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
        (point_index, state.instrument_id, field.value.root)
        for point_index, state, field in materialized_state_fields(preview)
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
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )
    module = (
        authoring.module_body(id="test.runtime_entity_dependent_points")
        .inputs(qubit)
        .resource("source", requires=("scalar_signal",))
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.runtime_entity_dependent_points",
        kind="runtime_entity_dependent_points",
        scans=(
            sc.axis(
                sc.coordinate("drive_length", _QUANTITY_VALUE),
                center=sc.parameter_lookup(
                    "sample_qubits",
                    key={"qubit": qubit},
                    column="rabi_length",
                    value_type=_QUANTITY_VALUE,
                ),
                span=Quantity(value=20.0, unit="ns"),
                points=3,
            ),
        ),
        records=(authoring.record_product(module.products.signal),),
    )

    resolved = link_invocation(template.bind(qubit="q0"), config_profile=config)
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
    module = (
        authoring.module_body(id="test.categorical_axis")
        .resource("source", requires=("scalar_signal",))
        .product(
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
        .acquire(
            "read-iq",
            "iq",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.categorical_axis",
        kind="categorical_axis",
        records=(authoring.record_product(module.products.iq),),
    )

    resolved = link_invocation(
        template.bind(),
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
    typed_value = sc.input(
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
    source = elaborate_module(SIMPLE_MODULE.ir, subject="q0")
    axis = _around_parameter_axis()
    assembly = replace(
        source,
        experiment_id="authored-simple-scan",
        kind="simple_scan",
        point_domain=lower_scans_point_domain((axis,)),
        parameter_contracts=scan_parameter_contracts(axis),
    )
    environment = build_config_environment(load_config())
    resolved = link_program(
        bind_verified_assembly(verify_assembly(assembly), environment),
        environment,
    )

    assert resolved.program.id == "authored-simple-scan"
    assert resolved.environment.config.id == load_config().id
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
    )
    assert materialized_state_fields(preview)[0][1].instrument_id == "source-0"


def test_link_validates_scan_axis_parameter_contracts() -> None:
    axis = _around_parameter_axis("missing_frequency")
    assembly = SemanticExperimentIR(
        experiment_id="missing-parameter-scan",
        kind="simple_scan",
        point_domain=lower_scans_point_domain((axis,)),
        parameter_contracts=scan_parameter_contracts(axis),
    )
    environment = build_config_environment(load_config())
    with pytest.raises(CheckFailed) as caught:
        link_program(
            bind_verified_assembly(verify_assembly(assembly), environment),
            environment,
        )

    assert caught.value.problems[0].code == "unknown_authoring_parameter"
    assert caught.value.problems[0].location == model_location(
        "parameters",
        "missing_frequency",
    )


def test_explicit_instances_keep_same_named_resource_ports_isolated() -> None:
    pulse = (
        authoring.module_body(id="test.shared_resource.pulse")
        .resource("source", requires=("set_frequency",))
        .build()
    )
    records = (
        authoring.module_body(id="test.shared_resource.records")
        .resource("source", requires=("acquire_signal",))
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="acquire_signal",
        )
        .build()
    )
    root = (
        authoring.module_body(id="test.shared_resource.root")
        .use(
            pulse.instantiate("pulse"),
            records.instantiate("records"),
        )
        .build()
    )

    assembly = elaborate_module(root.ir)
    assert [port.symbol_id for port in assembly.resource_ports] == [
        logical_resource_port_id(SymbolId(scope=("pulse",), local_id="source")),
        logical_resource_port_id(SymbolId(scope=("records",), local_id="source")),
    ]
    assert [port.selector.capabilities for port in assembly.resource_ports] == [
        ("set_frequency",),
        ("acquire_signal",),
    ]


def test_module_construction_rejects_duplicate_resource_ids() -> None:
    with pytest.raises(ValueError, match="duplicate module resource ids"):
        (
            authoring.module_body(id="test.shared_resource.duplicate")
            .resource("source", requires=("set_frequency",))
            .resource("source", requires=("acquire_signal",))
            .build()
        )


def test_template_composition_rejects_duplicate_record_ids() -> None:
    first = _module_fixture(
        id="test.duplicate_record.first",
        resources=[
            resource_port(
                "source",
                requires("set_frequency", "scalar_signal"),
            ),
        ],
        products=[_observable_product("signal", unit="ratio")],
    )
    second = _module_fixture(
        id="test.duplicate_record.second",
        entity_inputs=(),
        resources=[resource_port("source", requires("set_frequency"))],
        products=[_observable_product("signal", unit="ratio")],
    )

    with pytest.raises(CheckFailed) as error:
        link_invocation(
            _template_invocation(
                first,
                second,
                id="test.duplicate_record",
                kind="simple_scan",
            ),
            config_profile=load_config(),
        )

    assert error.value.problems[0].code == "experiment_record_duplicate"


def test_elaboration_invocation_literals_bind_local_inputs() -> None:
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module_body(id="test.invocation_defaults.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=drive_frequency,
        )
        .build()
    )
    parent = (
        authoring.module_body(id="test.invocation_defaults.parent")
        .use(
            child.instantiate(
                "defaults-child",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )
        .build()
    )

    assembly = elaborate_module(
        parent.ir,
    )

    assert "drive_frequency" not in assembly.inputs
    assert all(port.id != "drive_frequency" for port in assembly.input_ports)
    assert isinstance(assembly.bindings[0].value, ValueRef)
    first_value = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert isinstance(first_value, LiteralScalarExpr)
    assert first_value.value == Quantity(value=5.0, unit="GHz")


def test_module_invocation_rejects_undeclared_inputs() -> None:
    child = authoring.module_body(id="test.invocation_unknown_input.child").build()

    with pytest.raises(ValueError, match="received undeclared inputs: 'frequency'"):
        child.instantiate(
            "unknown-input-child",
            frequency=Quantity(value=5.0, unit="GHz"),
        )


def test_elaboration_invocation_expressions_bind_local_inputs() -> None:
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module_body(id="test.invocation_override.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=drive_frequency,
        )
        .build()
    )
    parent = (
        authoring.module_body(id="test.invocation_expression.parent")
        .use(
            child.instantiate(
                "expression-child",
                drive_frequency=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType()),
                ),
            )
        )
        .build()
    )

    assembly = elaborate_module(
        parent.ir,
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    assert internal_lower_value_ref(assembly.bindings[0].value) == param(
        "drive_frequency"
    )


def test_elaboration_defers_nested_expression_and_literal_bindings() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    child_value = authoring.input(
        "child_value",
        value_type,
    )
    unused_parameter = authoring.input("unused_parameter", value_type)
    unused_point = authoring.input("unused_point", value_type)
    child = (
        authoring.module_body(id="test.invocation_deferred.child")
        .inputs(child_value, unused_parameter, unused_point)
        .resource("source", requires=("set_offset",))
        .bind_field(
            "source",
            capability="set_offset",
            field="offset",
            value=child_value,
        )
        .build()
    )
    parent_value = authoring.input(
        "parent_value",
        value_type,
    )
    parent = (
        authoring.module_body(id="test.invocation_deferred.parent")
        .inputs(parent_value)
        .use(
            child.instantiate(
                "deferred-child",
                child_value=parent_value + 0.25,
                unused_parameter=authoring.parameter(
                    "unused_parameter",
                    value_type,
                ),
                unused_point=authoring.coordinate("unused_point", value_type),
            )
        )
        .build()
    )
    root = (
        authoring.module_body(id="test.invocation_deferred.root")
        .use(parent.instantiate("deferred-parent", parent_value=1.5))
        .build()
    )

    assembly = elaborate_module(root.ir)

    assert isinstance(assembly.bindings[0].value, ValueRef)
    expression = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert evaluate_scalar(expression, EvalContext()) == 1.75
    assert internal_value_ref_parameter_contracts(assembly.bindings[0].value) == ()
    assert internal_value_ref_point_dependencies(assembly.bindings[0].value) == ()
    assert assembly.parameter_contracts == ()
    assert assembly.point_dependencies == ()


def test_module_provenance_follows_only_reachable_input_bindings() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    used_parameter_input = authoring.input("used_parameter", value_type)
    unused_parameter_input = authoring.input("unused_parameter", value_type)
    used_point_input = authoring.input("used_point", value_type)
    unused_point_input = authoring.input("unused_point", value_type)
    module = (
        authoring.module_body(id="test.reachable-input-provenance")
        .inputs(
            used_parameter_input,
            unused_parameter_input,
            used_point_input,
            unused_point_input,
        )
        .resource("source", requires=("set_offset", "set_gain"))
        .bind_field(
            "source",
            capability="set_offset",
            field="offset",
            value=used_parameter_input,
        )
        .bind_field(
            "source",
            capability="set_gain",
            field="gain",
            value=used_point_input,
        )
        .build()
    )
    used_parameter = authoring.parameter("reachable_parameter", value_type)
    unused_parameter = authoring.parameter("phantom_parameter", value_type)
    used_point = authoring.coordinate("reachable_point", value_type)
    unused_point = authoring.coordinate("phantom_point", value_type)

    assembly = elaborate_module(
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
    child_value = authoring.input("value", value_type)
    parent_value = authoring.input("value", value_type)

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
    parent_b = authoring.input("b", value_type)
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
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    outer_frequency = authoring.input(
        "outer_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module_body(id="test.invocation_parent_input.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=drive_frequency,
        )
        .build()
    )
    parent = (
        authoring.module_body(id="test.invocation_parent_input.parent")
        .inputs(outer_frequency)
        .use(
            child.instantiate(
                "parent-input-child",
                drive_frequency=outer_frequency,
            )
        )
        .build()
    )

    assembly = elaborate_module(
        parent.ir, outer_frequency=Quantity(value=5.2, unit="GHz")
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    localized = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert isinstance(localized, InputScalarExpr)
    assert localized.name == "outer_frequency"


def test_elaboration_does_not_merge_sibling_invocation_inputs() -> None:
    first_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    first = (
        authoring.module_body(id="test.invocation_sibling.first")
        .inputs(first_frequency)
        .resource("source", requires=("set_frequency",))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=first_frequency,
        )
        .build()
    )
    second_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    second = (
        authoring.module_body(id="test.invocation_sibling.second")
        .inputs(second_frequency)
        .resource("detector", requires=("set_frequency",))
        .bind_field(
            "detector",
            capability="set_frequency",
            field="frequency",
            value=second_frequency,
        )
        .build()
    )

    module = (
        authoring.module_body(id="test.invocation_sibling.parent")
        .use(
            first.instantiate(
                "first",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            ),
            second.instantiate(
                "second",
                drive_frequency=Quantity(value=5.1, unit="GHz"),
            ),
        )
        .build()
    )

    assembly = elaborate_module(
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
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module_body(id="test.invocation_entity.child")
        .inputs(qubit, drive_frequency)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind_field(
            "drive",
            capability="set_frequency",
            field="frequency",
            value=drive_frequency,
        )
        .build()
    )
    parent = (
        authoring.module_body(id="test.invocation_entity.parent")
        .use(
            child.instantiate(
                "entity-child",
                qubit="q0",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )
        .build()
    )

    assembly = elaborate_module(
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
    prelude = _module_fixture(id="test.scripted_module_prelude")
    scan = _module_fixture(
        id="test.scripted_module_scan",
        resources=[
            resource_port(
                "source",
                requires("set_frequency", "scalar_signal"),
            ),
        ],
        bindings=[
            bind_field(
                "source",
                capability="set_frequency",
                field="frequency",
                value=DRIVE_FREQUENCY_POINT,
            )
        ],
        products=[_observable_product("signal", unit="ratio")],
    )

    resolved = link_invocation(
        _template_invocation(
            prelude,
            scan,
            id="test.scripted_scan",
            kind="simple_scan",
        ).scan(
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
    module = _module_fixture(
        id="test.record_axes",
        resources=[
            resource_port(
                "source",
                requires("set_frequency", "scalar_signal"),
            ),
        ],
        bindings=[
            bind_field(
                "source",
                capability="set_frequency",
                field="frequency",
                value=DRIVE_FREQUENCY_POINT,
            ),
        ],
        products=[
            _observable_product(
                "signal",
                unit="ratio",
                axes=(
                    authoring.shot_axis(2),
                    authoring.product_axis("repetition", size=3, kind="repetition"),
                ),
            )
        ],
    )

    resolved = link_invocation(
        _template_invocation(
            module,
            id="test.record_axes",
            kind="simple_scan",
        ).scan(
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


def test_module_invocation_resolves_multiple_entity_inputs() -> None:
    module = _module_fixture(
        id="test.multi_entity",
        entity_inputs=("device", "drive_channel"),
    )

    resolved = link_invocation(
        _template_invocation(
            module,
            id="authored-multi-entity",
            kind="multi_entity",
            inputs={"device": "q0", "drive_channel": "drive-q0"},
        ),
        config_profile=load_config(),
    )

    assert resolved.program.id == "authored-multi-entity"


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
                        source_0.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="source-0",
                        capability="set_frequency",
                        entity_id="q0",
                        channel_id="drive-q0",
                    ),
                    RoutingEndpointBinding(
                        instrument_id="source-1",
                        capability="set_frequency",
                        entity_id="q1",
                        channel_id="drive-q1",
                    ),
                ],
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module_body(id="test.entity_selected_resource")
        .inputs(qubit)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind_field(
            "drive",
            capability="set_frequency",
            field="frequency",
            value=authoring.parameter(
                "drive_frequency",
                authoring.ScalarType(authoring.QuantityType(unit="GHz")),
            ),
        )
        .build()
    )

    resolved = link_invocation(
        template_fixture(
            module,
            id="test.entity_selected_resource",
            kind="entity_selected_resource",
        ).bind(qubit="q1"),
        config_profile=config,
    )

    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )
    assert materialized_state_fields(preview)[0][1].instrument_id == "source-1"


def test_explicit_config_links_experiment() -> None:
    selected_instrument = "spare-awg"
    config = config_with_physical_resources({selected_instrument: ("drive.frequency",)})
    module = (
        authoring.module_body(id="test.explicit-config-source")
        .resource("drive", requires=("drive.frequency",))
        .bind_field(
            "drive",
            capability="drive.frequency",
            field="value",
            value=Quantity(value=5.0, unit="GHz"),
        )
        .build()
    )

    resolved = link_invocation(
        template_fixture(
            module,
            id="test.explicit-config-source",
            kind="config-source",
        ).bind(),
        config_profile=config,
    )
    preview = materialized_effects_contract(
        resolved.program,
        resolved.environment.parameters,
        config=config,
    )

    assert materialized_state_fields(preview)[0][1].instrument_id == selected_instrument
    assert resolved.environment.config is config


def test_module_assembler_reports_ambiguous_resource_port() -> None:
    seed_config = load_config()
    system = seed_config.system.model_copy(
        update={
            "instrument_registry": seed_config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        *seed_config.instrument_registry.instruments,
                        seed_config.instrument_registry.instruments[0].model_copy(
                            update={"id": "source-1"}
                        ),
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id=resource_id,
                        capability=capability,
                    )
                    for resource_id in ("source-0", "source-1")
                    for capability in ("set_frequency", "scalar_signal")
                ],
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})

    resolved = link_invocation(
        simple_template().bind(subject="q0"),
        config_profile=config,
    )
    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(
            resolved.program,
            resolved.environment.parameters,
            config=config,
        )

    assert failure.value.problems[0].code == "module_resource_port_ambiguous"
