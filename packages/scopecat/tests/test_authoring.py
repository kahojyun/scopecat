from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import scopecat as sc
import scopecat.authoring as authoring
from scopecat._workflows.config import register_and_activate_config_profile
from scopecat.authoring import (
    resolve_experiment,
)
from scopecat.authoring.assembly import ComputeNodeIntent, ExperimentAssembly
from scopecat.authoring.resolution import _link_assembly
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
    RunRequest,
)
from scopecat.models.config import RoutingGraph, RoutingResource
from scopecat.models.entity import EntityRef, entity_array
from scopecat.models.parameter import (
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    Quantity,
)
from scopecat.parameters import ParameterDerivationSet, ScalarParameterDerivation
from scopecat.relations import RelationExpr, param
from tests.support.authoring import (
    SIMPLE_MODULE,
    load_config,
    simple_template,
)
from tests.support.authoring import (
    parameter_view as _parameter_view,
)
from tests.support.experiment_preview import preview_contract, preview_result


def _around_parameter_points(
    parameter_id: str = "drive_frequency",
    *,
    points: int = 5,
) -> RelationExpr:
    return sc.axis(
        parameter_id,
        center=param(parameter_id),
        span=Quantity(value=200.0, unit="MHz"),
        points=points,
    ).points


def _module_fixture(
    *,
    id: str,  # noqa: A002
    entity_inputs: Sequence[str] = (),
    resources: Sequence[authoring.ResourcePort] = (),
    variables: Sequence[authoring.VariableIntent] = (),
    bindings: Sequence[authoring.ExperimentBindingIntent] = (),
    state_intents: Sequence[authoring.ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[authoring.RecordIntent] = (),
    product_ports: Sequence[authoring.ModuleProductPort] = (),
    parameter_derivations: ParameterDerivationSet | None = None,
) -> authoring.ExperimentModule:
    return authoring.ExperimentModule(
        id=id,
        entity_inputs=tuple(entity_inputs),
        resource_ports=tuple(resources),
        variables=tuple(variables),
        bindings=tuple(bindings),
        state_intents=tuple(state_intents),
        compute_nodes=tuple(compute_nodes),
        records=tuple(records),
        product_ports=tuple(product_ports),
        parameter_derivations=parameter_derivations,
    )


def _template_invocation(
    *sources: authoring.ExperimentModule,
    id: str,  # noqa: A002
    kind: str,
    experiment_id: str | None = None,
    inputs: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> authoring.ExperimentInvocation:
    template = authoring.template(id, kind=kind).use(*sources)
    if experiment_id is not None:
        template = template.experiment_id(experiment_id)
    if metadata is not None:
        template = template.metadata(**metadata)
    return template.bind(**dict(inputs or {}))


def test_module_invocation_resolves_roles_scans_bindings_and_metadata() -> None:
    resolved = resolve_experiment(
        simple_template().bind(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert resolved.template_id == "test.simple_scan"
    experiment = resolved.experiment
    assert isinstance(experiment, ExperimentSpec)
    assert experiment.id == "authored-simple-scan"
    assert experiment.kind == "simple_scan"
    assert experiment.metadata == {"assembled_by": "template"}
    preview = preview_contract(experiment, _parameter_view(), config=load_config())

    assert preview.coordinate_ids == ("drive_frequency",)
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert [record.id for record in experiment.records] == ["signal"]
    assert preview.primary_observables == ("signal",)
    assert preview.state_changes[0].resource == "source"
    assert preview.state_changes[0].field == "set_frequency.frequency"
    assert preview.state_changes[0].after == Quantity(value=4.9, unit="GHz")
    assert preview.state_fields[0].resource_id == "source-0"


def test_template_selects_module_products_as_records() -> None:
    module = (
        authoring.module("test.product_module")
        .entity("subject")
        .resource("source", requires=("set_frequency",))
        .product("signal", resource="source", unit="ratio")
        .build()
    )
    without_selection = (
        authoring.template("test.product_unselected", kind="product_test")
        .experiment_id("product-unselected")
        .scan("drive_frequency", [4.9, 5.0, 5.1], unit="GHz")
        .use(module)
        .build()
    )
    with_selection = (
        authoring.template("test.product_selected", kind="product_test")
        .experiment_id("product-selected")
        .scan("drive_frequency", [4.9, 5.0, 5.1], unit="GHz")
        .use(module)
        .record_product("signal")
        .build()
    )

    unselected = resolve_experiment(
        without_selection.bind(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    selected = resolve_experiment(
        with_selection.bind(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert unselected.experiment.records == []
    assert [record.id for record in selected.experiment.records] == ["signal"]
    assert selected.experiment.records[0].metadata == {"product_id": "signal"}


def test_compute_inputs_keep_template_input_provenance() -> None:
    def build_program(**inputs: object) -> dict[str, object]:
        return dict(inputs)

    module = (
        authoring.module("test.compute_provenance")
        .input("qubit", kind="entity")
        .input("pulse_length", kind="quantity")
        .resource("drive", requires=("play_pulse_program",))
        .compute(
            "build-program",
            fn=build_program,
            inputs={
                "qubit": authoring.input_ref("qubit"),
                "length": authoring.input_ref("pulse_length"),
                "frequency": param(
                    "sample_qubits",
                    key={"qubit": authoring.input_ref("qubit")},
                    column="drive_frequency",
                ),
            },
        )
        .bind_compute("drive.play_pulse_program.program", "build-program", kind="pulse")
        .build()
    )
    template = (
        authoring.template("test.compute_provenance", kind="compute_provenance")
        .experiment_id("compute-provenance")
        .use(module)
        .defaults(pulse_length=Quantity(value=20.0, unit="ns"))
        .build()
    )

    resolved = resolve_experiment(
        template.bind(qubit="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]

    assert node.inputs["qubit"].source_inputs == ["qubit"]
    assert node.inputs["length"].source_inputs == ["pulse_length"]
    assert node.inputs["frequency"].source_inputs == ["qubit"]


def test_template_can_scan_entity_input_without_subject_special_case() -> None:
    module = (
        authoring.module("test.entity_scan_module")
        .input("qubit", kind="entity")
        .product("signal", resource="source", unit="ratio")
        .build()
    )
    template = (
        authoring.template("test.entity_scan", kind="entity_scan")
        .experiment_id("entity-scan")
        .scan("qubit", [EntityRef(id="q0", kind="logical_device")])
        .use(module)
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview = preview_contract(resolved.experiment, resolved.parameter_view)

    assert preview.points[0].coordinates["qubit"] == EntityRef(
        id="q0", kind="logical_device"
    )
    assert preview.schema is not None
    coordinate = next(
        variable for variable in preview.schema.variables if variable.id == "qubit"
    )
    assert coordinate.dtype == "string"
    assert coordinate.metadata == {"entity_kind": "logical_device"}


def test_entity_scan_routes_resources_per_point() -> None:
    seed_config = load_config()
    q0 = seed_config.topology.devices[0]
    drive_q0 = seed_config.topology.channels[0]
    source_0 = seed_config.instrument_registry.instruments[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
                EntityRef(id="drive-q1", kind="drive_channel"),
            ],
            "devices": [
                *seed_config.topology.devices,
                q0.model_copy(update={"id": "q1", "channels": ["drive-q1"]}),
            ],
            "channels": [
                *seed_config.topology.channels,
                drive_q0.model_copy(update={"id": "drive-q1", "device_id": "q1"}),
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
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                        served_entities=["q0"],
                        channels=["drive-q0"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                        served_entities=["q1"],
                        channels=["drive-q1"],
                    ),
                ]
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})
    module = (
        authoring.module("test.entity_scan_routing")
        .entity("qubit")
        .resource(
            "drive",
            requires=authoring.requires("set_frequency", for_entities=("qubit",)),
        )
        .bind("drive.set_frequency.frequency", Quantity(value=5.0, unit="GHz"))
        .product("signal", resource="drive", unit="ratio")
        .build()
    )
    template = (
        authoring.template("test.entity_scan_routing", kind="entity_scan_routing")
        .experiment_id("entity-scan-routing")
        .scan(
            "qubit",
            [
                EntityRef(id="q0", kind="logical_device"),
                EntityRef(id="q1", kind="logical_device"),
            ],
        )
        .use(module)
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )

    assert [point.point_index for point in preview.points] == [0, 1]
    assert [route.resource_id for route in preview.routes[0].resolved] == [
        "source-0",
        "source-1",
    ]
    assert [field.resource_id for field in preview.state_fields] == [
        "source-0",
        "source-1",
    ]


def test_runtime_entity_scan_feeds_routing_and_parameter_lookup() -> None:
    seed_config = load_config()
    q0 = seed_config.topology.devices[0]
    drive_q0 = seed_config.topology.channels[0]
    source_0 = seed_config.instrument_registry.instruments[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
                EntityRef(id="drive-q1", kind="drive_channel"),
            ],
            "devices": [
                *seed_config.topology.devices,
                q0.model_copy(update={"id": "q1", "channels": ["drive-q1"]}),
            ],
            "channels": [
                *seed_config.topology.channels,
                drive_q0.model_copy(update={"id": "drive-q1", "device_id": "q1"}),
            ],
        }
    )
    catalog = seed_config.parameter_catalog.model_copy(
        update={
            "table_definitions": [
                *seed_config.parameter_catalog.table_definitions,
                ParameterTableDefinition(
                    id="sample_qubits",
                    primary_key=["qubit"],
                    columns=[
                        ParameterTableColumn(id="qubit", kind="string"),
                        ParameterTableColumn(
                            id="drive_frequency",
                            kind="quantity",
                            unit="GHz",
                        ),
                    ],
                ),
            ]
        }
    )
    parameter_state = seed_config.parameter_state.model_copy(
        update={
            "tables": [
                *seed_config.parameter_state.tables,
                ParameterTable(
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
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                        served_entities=["q0"],
                        channels=["drive-q0"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                        served_entities=["q1"],
                        channels=["drive-q1"],
                    ),
                ]
            ),
        }
    )
    config = seed_config.model_copy(
        update={"system": system, "parameter_state": parameter_state}
    )
    module = (
        authoring.module("test.runtime_entity_scan")
        .entity("qubit")
        .resource(
            "drive",
            requires=authoring.requires("set_frequency", for_entities=("qubit",)),
        )
        .bind(
            "drive.set_frequency.frequency",
            param(
                "sample_qubits",
                key={"qubit": authoring.input_ref("qubit")},
                column="drive_frequency",
            ),
        )
        .product("signal", resource="drive", unit="ratio")
        .build()
    )
    template = (
        authoring.template("test.runtime_entity_scan", kind="runtime_entity_scan")
        .experiment_id("runtime-entity-scan")
        .use(module)
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind().scan("qubit", ["q0", "q1"]),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )

    assert [point.coordinates["qubit"] for point in preview.points] == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]
    assert [route.resource_id for route in preview.routes[0].resolved] == [
        "source-0",
        "source-1",
    ]
    assert [
        (field.point_index, field.resource_id, field.value)
        for field in preview.state_fields
    ] == [
        (0, "source-0", Quantity(value=5.0, unit="GHz")),
        (1, "source-1", Quantity(value=5.1, unit="GHz")),
    ]


def test_runtime_entity_scan_can_drive_dependent_default_scan() -> None:
    seed_config = load_config()
    q0 = seed_config.topology.devices[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
            "devices": [
                *seed_config.topology.devices,
                q0.model_copy(update={"id": "q1", "channels": []}),
            ],
        }
    )
    catalog = seed_config.parameter_catalog.model_copy(
        update={
            "table_definitions": [
                *seed_config.parameter_catalog.table_definitions,
                ParameterTableDefinition(
                    id="sample_qubits",
                    primary_key=["qubit"],
                    columns=[
                        ParameterTableColumn(id="qubit", kind="string"),
                        ParameterTableColumn(
                            id="rabi_length",
                            kind="quantity",
                            unit="ns",
                        ),
                    ],
                ),
            ]
        }
    )
    parameter_state = seed_config.parameter_state.model_copy(
        update={
            "tables": [
                *seed_config.parameter_state.tables,
                ParameterTable(
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
        update={"system": system, "parameter_state": parameter_state}
    )
    module = (
        authoring.module("test.runtime_entity_dependent_points")
        .entity("qubit")
        .product("signal", unit="ratio")
        .build()
    )
    template = (
        authoring.template(
            "test.runtime_entity_dependent_points",
            kind="runtime_entity_dependent_points",
        )
        .experiment_id("runtime-entity-dependent-points")
        .scan(
            "drive_length",
            center=param(
                "sample_qubits",
                key={"qubit": authoring.input_ref("qubit")},
                column="rabi_length",
            ),
            span=Quantity(value=20.0, unit="ns"),
            points=3,
        )
        .use(module)
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind().scan("qubit", ["q0", "q1"]),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )

    assert [
        (point.coordinates["qubit"], point.coordinates["drive_length"])
        for point in preview.points
    ] == [
        (EntityRef(id="q0", kind="logical_device"), Quantity(value=30.0, unit="ns")),
        (EntityRef(id="q0", kind="logical_device"), Quantity(value=40.0, unit="ns")),
        (EntityRef(id="q0", kind="logical_device"), Quantity(value=50.0, unit="ns")),
        (EntityRef(id="q1", kind="logical_device"), Quantity(value=70.0, unit="ns")),
        (EntityRef(id="q1", kind="logical_device"), Quantity(value=80.0, unit="ns")),
        (EntityRef(id="q1", kind="logical_device"), Quantity(value=90.0, unit="ns")),
    ]


def test_entity_array_input_can_define_record_axis() -> None:
    module = (
        authoring.module("test.entity_array_axis_module")
        .input("qubits", kind="entity_array")
        .product(
            "iq",
            resource="source",
            dtype="complex128",
            axes=(authoring.entity_axis("qubit", authoring.input_ref("qubits")),),
        )
        .build()
    )
    template = (
        authoring.template("test.entity_array_axis", kind="entity_array_axis")
        .experiment_id("entity-array-axis")
        .use(module)
        .record_product("iq")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(qubits=entity_array(["q0"])),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    axis = resolved.experiment.records[0].axes[0]
    assert axis.id == "qubit"
    assert axis.kind == "entity"
    assert axis.size == 1
    assert axis.metadata == {
        "entity_kind": "logical_device",
        "entities": [{"id": "q0", "kind": "logical_device", "metadata": {}}],
    }


def test_entity_array_routes_as_single_point_with_ordered_product_axis() -> None:
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
                    "instruments": [source_0.model_copy(update={"id": "readout-array"})]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="readout-array",
                        capabilities=["set_frequency"],
                        served_entities=["q0", "q1"],
                    )
                ]
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})
    module = (
        authoring.module("test.entity_array_routing")
        .input("qubits", kind="entity_array")
        .resource(
            "readout",
            requires=authoring.requires("set_frequency", for_entities=("qubits",)),
        )
        .product(
            "iq",
            resource="readout",
            dtype="complex128",
            axes=(authoring.entity_axis("qubit", authoring.input_ref("qubits")),),
        )
        .build()
    )
    template = (
        authoring.template("test.entity_array_routing", kind="entity_array_routing")
        .experiment_id("entity-array-routing")
        .use(module)
        .record_product("iq")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(qubits=entity_array(["q0", "q1"])),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )

    assert preview.point_count == 1
    binding = preview.routes[0].resolved[0]
    assert binding.resource_id == "readout-array"
    assert binding.entity_ids == ("q0", "q1")
    assert binding.product_axis_order == ("q0", "q1")
    assert preview.records[0].resource == "readout"
    assert preview.records[0].dims == ("point", "qubit")
    assert preview.records[0].shape == (1, 2)


def test_module_invocation_compiles_to_assembly_without_config_or_request() -> None:
    invocation = SIMPLE_MODULE(subject="q0")
    assembly = invocation.assemble()

    assert isinstance(invocation, authoring.ModuleInvocation)
    assert isinstance(assembly, ExperimentAssembly)
    assert assembly.experiment_id is None
    assert assembly.kind is None
    assert assembly.request is None
    assert assembly.inputs == {"subject": "q0"}
    assert assembly.resource_ports[0].id == "source"


def test_link_assembly_resolves_config_dependent_fragments() -> None:
    source = SIMPLE_MODULE(subject="q0").assemble()
    points = ExperimentAssembly(point_source=_around_parameter_points())
    assembly = ExperimentAssembly.combine(
        experiment_id="authored-simple-scan",
        kind="simple_scan",
        assemblies=(points, source),
    ).with_invocation(
        request=RunRequest(
            id="simple.request",
            template_id="test.simple_scan",
            template_inputs={"subject": "q0"},
        ),
        inputs={"subject": "q0"},
        parameter_derivations=None,
    )

    resolved = _link_assembly(
        assembly,
        config=load_config(),
        workspace=Path("/tmp/scopecat-test"),
        config_source=None,
    )

    assert resolved.experiment.id == "authored-simple-scan"
    assert resolved.experiment.config_snapshot_id == load_config().id
    preview = preview_contract(resolved.experiment, resolved.parameter_view)
    assert preview.state_changes[0].resource == "source"


def test_short_authoring_helpers_lower_to_plan() -> None:
    module = _module_fixture(
        id="test.short_helpers",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        variables=[
            authoring.derive(
                "drive_detuning",
                authoring.var_ref("drive_frequency")
                - authoring.param_ref("drive_frequency"),
            ),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_frequency"),
            ),
        ],
        records=[authoring.observable("signal", resource="source", unit="ratio")],
    )

    resolved = resolve_experiment(
        _template_invocation(
            module,
            id="test.short_helpers",
            experiment_id="short-helper-scan",
            kind="simple_scan",
            inputs={"subject": "q0"},
        ).scan(
            "drive_frequency",
            center=param("drive_frequency"),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview = preview_contract(resolved.experiment, _parameter_view())

    assert resolved.experiment.id == "short-helper-scan"
    assert preview.coordinate_ids == ("drive_frequency", "drive_detuning")
    assert preview.state_changes[0].field == "set_frequency.frequency"


def test_template_composition_merges_shared_resource_port_capabilities() -> None:
    pulse = _module_fixture(
        id="test.shared_resource.pulse",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.param_ref("drive_frequency"),
            )
        ],
    )
    records = _module_fixture(
        id="test.shared_resource.records",
        entity_inputs=(),
        resources=[
            authoring.resource_port("source", authoring.requires("acquire_signal")),
        ],
        records=[authoring.observable("signal", resource="source", unit="ratio")],
    )

    compiled = _template_invocation(
        pulse,
        records,
        id="test.shared_resource",
        kind="simple_scan",
        inputs={"subject": "q0"},
    ).compile()

    assert isinstance(compiled, ExperimentAssembly)
    assembly = compiled
    assert len(assembly.resource_ports) == 1
    assert assembly.resource_ports[0].id == "source"
    assert assembly.resource_ports[0].selector.capabilities == (
        "set_frequency",
        "acquire_signal",
    )


def test_template_composition_rejects_duplicate_record_ids() -> None:
    first = _module_fixture(
        id="test.duplicate_record.first",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        records=[authoring.observable("signal", resource="source", unit="ratio")],
    )
    second = _module_fixture(
        id="test.duplicate_record.second",
        entity_inputs=(),
        records=[authoring.observable("signal", resource="source", unit="ratio")],
    )

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            _template_invocation(
                first,
                second,
                id="test.duplicate_record",
                kind="simple_scan",
                inputs={"subject": "q0"},
            ),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    assert error.value.diagnostics[0].code == "module_record_duplicate"


def test_combined_module_parameter_derivations_chain_in_order() -> None:
    first = ExperimentAssembly(
        entity_inputs=(),
        parameter_derivations=ParameterDerivationSet(
            id="derive-drive-base",
            scalars=[
                ScalarParameterDerivation(
                    id="drive_base",
                    expression=param("drive_frequency")
                    + Quantity(value=0.1, unit="GHz"),
                )
            ],
        ),
    )
    second = ExperimentAssembly(
        entity_inputs=(),
        parameter_derivations=ParameterDerivationSet(
            id="derive-drive-final",
            scalars=[
                ScalarParameterDerivation(
                    id="drive_final",
                    expression=param("drive_base") + Quantity(value=0.1, unit="GHz"),
                )
            ],
        ),
    )
    main = _module_fixture(
        id="test.combined",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_final"),
            )
        ],
    )(subject="q0").assemble()
    assembly = ExperimentAssembly.combine(
        experiment_id="combined-scan",
        kind="simple_scan",
        assemblies=(
            first,
            second,
            ExperimentAssembly(point_source=_around_parameter_points("drive_final")),
            main,
        ),
    ).with_invocation(
        request=RunRequest(
            id="combined.request",
            template_id="test.combined",
            template_inputs={"subject": "q0"},
        ),
        inputs={"subject": "q0"},
        parameter_derivations=None,
    )

    resolved = _link_assembly(
        assembly,
        config=load_config(),
        workspace=Path("/tmp/scopecat-test"),
        config_source=None,
    )
    preview, _ = preview_result(
        resolved.experiment,
        resolved.parameter_view,
        derivations=resolved.parameter_derivations,
    )

    final_parameter = resolved.parameter_view.get("drive_final")
    assert final_parameter is not None
    assert final_parameter.quantity == Quantity(value=5.2, unit="GHz")
    assert preview.points[0].coordinates["drive_final"] == Quantity(
        value=5.1, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_final"] == Quantity(
        value=5.3, unit="GHz"
    )


def test_template_invocation_runs_module_sources_directly() -> None:
    derived = ExperimentAssembly(
        entity_inputs=(),
        parameter_derivations=ParameterDerivationSet(
            id="derive-drive-final",
            scalars=[
                ScalarParameterDerivation(
                    id="drive_final",
                    expression=param("drive_frequency")
                    + Quantity(value=0.1, unit="GHz"),
                )
            ],
        ),
    )
    scan = _module_fixture(
        id="test.scripted_source_scan",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_frequency"),
            )
        ],
        records=[authoring.observable("signal", resource="source", unit="ratio")],
    )

    resolved = resolve_experiment(
        _template_invocation(
            _module_fixture(
                id="test.scripted_source_derived",
                parameter_derivations=derived.parameter_derivations,
            ),
            scan,
            id="test.scripted_scan",
            kind="simple_scan",
            inputs={"subject": "q0"},
        ).scan(
            "drive_frequency",
            center=param("drive_final"),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview, _ = preview_result(
        resolved.experiment,
        resolved.parameter_view,
        derivations=resolved.parameter_derivations,
    )

    assert resolved.template_id == "test.scripted_scan"
    assert resolved.inputs == {"subject": "q0"}
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=5.0, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.2, unit="GHz"
    )


def test_module_parameter_derivations_feed_authoring_and_planning() -> None:
    module = _module_fixture(
        id="test.derived_parameters",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_frequency"),
            )
        ],
        parameter_derivations=ParameterDerivationSet(
            id="module-parameter-graph",
            scalars=[
                ScalarParameterDerivation(
                    id="drive_frequency",
                    expression=param("drive_frequency")
                    + Quantity(value=0.1, unit="GHz"),
                )
            ],
        ),
    )

    resolved = resolve_experiment(
        _template_invocation(
            module,
            id="test.derived_parameters",
            experiment_id="derived-parameter-scan",
            kind="simple_scan",
            inputs={"subject": "q0"},
        ).scan(
            "drive_frequency",
            center=param("drive_frequency"),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview, _ = preview_result(
        resolved.experiment,
        resolved.parameter_view,
        derivations=resolved.parameter_derivations,
    )

    derived_drive = resolved.parameter_view.get("drive_frequency")
    assert resolved.parameter_derivations is not None
    assert derived_drive is not None
    assert derived_drive.quantity == Quantity(
        value=5.1,
        unit="GHz",
    )
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=5.0, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.2, unit="GHz"
    )


def test_link_assembly_reports_duplicate_variables() -> None:
    module = _module_fixture(
        id="test.duplicate_variables",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        variables=[
            authoring.variable(
                "drive_frequency",
                authoring.param_ref("drive_frequency"),
            ),
            authoring.variable(
                "drive_frequency",
                authoring.param_ref("drive_frequency"),
            ),
        ],
    )

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            _template_invocation(
                module,
                id="test.duplicate_variables",
                experiment_id="duplicate-variable-scan",
                kind="simple_scan",
                inputs={"subject": "q0"},
            ),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    assert error.value.diagnostics[0].code == "module_variable_duplicate"


def test_module_uses_record_axes() -> None:
    module = _module_fixture(
        id="test.record_axes",
        resources=[
            authoring.resource_port("source", authoring.requires("set_frequency")),
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_frequency"),
            ),
        ],
        records=[
            authoring.observable(
                "signal",
                resource="source",
                unit="ratio",
                axes=(
                    authoring.shot_axis(2),
                    authoring.record_axis("repetition", size=3, kind="repetition"),
                ),
            )
        ],
    )

    resolved = resolve_experiment(
        _template_invocation(
            module,
            id="test.record_axes",
            experiment_id="record-axes-scan",
            kind="simple_scan",
            inputs={"subject": "q0"},
        ).scan(
            "drive_frequency",
            center=param("drive_frequency"),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert len(resolved.experiment.records) == 1
    record = resolved.experiment.records[0]
    assert record.id == "signal"
    assert [axis.id for axis in record.axes] == ["shot", "repetition"]
    assert [axis.size for axis in record.axes] == [2, 3]


def test_module_invocation_resolves_multiple_entity_inputs() -> None:
    module = _module_fixture(
        id="test.multi_entity",
        entity_inputs=("device", "drive_channel"),
    )

    resolved = resolve_experiment(
        _template_invocation(
            module,
            id="test.multi_entity",
            experiment_id="authored-multi-entity",
            kind="multi_entity",
            inputs={"device": "q0", "drive_channel": "drive-q0"},
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert resolved.experiment.id == "authored-multi-entity"


def test_resource_port_can_select_by_fixed_entity_input() -> None:
    seed_config = load_config()
    q0 = seed_config.topology.devices[0]
    drive_q0 = seed_config.topology.channels[0]
    source_0 = seed_config.instrument_registry.instruments[0]
    topology = seed_config.topology.model_copy(
        update={
            "entities": [
                *seed_config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
                EntityRef(id="drive-q1", kind="drive_channel"),
            ],
            "devices": [
                *seed_config.topology.devices,
                q0.model_copy(update={"id": "q1", "channels": ["drive-q1"]}),
            ],
            "channels": [
                *seed_config.topology.channels,
                drive_q0.model_copy(update={"id": "drive-q1", "device_id": "q1"}),
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
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                        served_entities=["q0"],
                        channels=["drive-q0"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                        served_entities=["q1"],
                        channels=["drive-q1"],
                    ),
                ]
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})
    module = (
        authoring.module("test.entity_routed_resource")
        .entity("qubit")
        .resource(
            "drive",
            requires=authoring.requires("set_frequency", for_entities=("qubit",)),
        )
        .bind("drive.set_frequency.frequency", param("drive_frequency"))
        .build()
    )

    resolved = resolve_experiment(
        (
            authoring.template(
                "test.entity_routed_resource",
                kind="entity_routed_resource",
            )
            .experiment_id("entity-routed-resource")
            .use(module)
        ).bind(qubit="q1"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )

    preview = preview_contract(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )
    resource = resolved.experiment.state[0].resource
    assert resource is not None
    assert resource.value is not None
    assert resource.value == "drive"
    assert preview.routes[0].resolved[0].resource_id == "source-1"
    assert preview.state_fields[0].resource_id == "source-1"


def test_module_can_materialize_background_state_from_parameter_table() -> None:
    seed_config = load_config()
    catalog = seed_config.parameter_catalog.model_copy(
        update={
            "table_definitions": [
                *seed_config.parameter_catalog.table_definitions,
                ParameterTableDefinition(
                    id="flux_bias",
                    primary_key=["resource_id"],
                    columns=[
                        ParameterTableColumn(id="resource_id", kind="string"),
                        ParameterTableColumn(
                            id="offset",
                            kind="quantity",
                            unit="arb",
                        ),
                    ],
                ),
            ]
        }
    )
    system = seed_config.system.model_copy(
        update={"parameter_catalog": catalog},
    )
    parameter_state = seed_config.parameter_state.model_copy(
        update={
            "tables": [
                *seed_config.parameter_state.tables,
                ParameterTable(
                    id="flux_bias",
                    rows=[
                        {
                            "resource_id": "flux-q0",
                            "offset": Quantity(value=0.1, unit="arb"),
                        },
                        {
                            "resource_id": "flux-q1",
                            "offset": Quantity(value=-0.2, unit="arb"),
                        },
                    ],
                ),
            ]
        }
    )
    config = seed_config.model_copy(
        update={"system": system, "parameter_state": parameter_state}
    )
    background = (
        authoring.module("test.background_flux")
        .state_table(
            "flux_bias",
            field="set_offset.offset",
            value_column="offset",
        )
        .build()
    )

    resolved = resolve_experiment(
        (
            authoring.template("test.background_flux", kind="background_flux")
            .experiment_id("background-flux")
            .use(background)
        ).bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(resolved.experiment, resolved.parameter_view)

    assert [
        (change.resource, change.field, change.after)
        for change in preview.state_changes
    ] == [
        ("flux-q0", "set_offset.offset", Quantity(value=0.1, unit="arb")),
        ("flux-q1", "set_offset.offset", Quantity(value=-0.2, unit="arb")),
    ]


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
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                    ),
                ]
            ),
        }
    )
    config = seed_config.model_copy(update={"system": system})

    resolved = resolve_experiment(
        simple_template().bind(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    _preview, diagnostics = preview_result(
        resolved.experiment,
        resolved.parameter_view,
        config=config,
    )

    assert diagnostics[0].code == "module_resource_port_ambiguous"


def test_resolve_experiment_uses_active_config_and_template_defaults(
    tmp_path: Path,
) -> None:
    register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    invocation = simple_template().bind(subject="q0")

    resolved = resolve_experiment(invocation, workspace=tmp_path)

    assert resolved.template_id == "test.simple_scan"
    assert resolved.config_source is not None
    assert resolved.config_source.entry_id == "seed"
    experiment = resolved.experiment
    assert isinstance(experiment, ExperimentSpec)
    preview = preview_contract(experiment, _parameter_view())

    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.1, unit="GHz"
    )
