from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import scopecat as sc
import scopecat.authoring as authoring
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    EvalContext,
    input_ref,
    param,
)
from scopecat._workflows.config import register_and_activate_config_profile
from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    bind,
    requires,
    resource_port,
)
from scopecat.authoring._intents import (  # pyright: ignore[reportPrivateUsage]
    ComputeNodeIntent,
    ExperimentStateIntent,
    ModuleInputPort,
)
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._module_composition import (
    ExperimentAssemblyInternal,
    assemble_invocation_internal,
    assemble_module_internal,
)
from scopecat.authoring._module_construction import module_from_parts_internal
from scopecat.authoring._record_intents import (  # pyright: ignore[reportPrivateUsage]
    ModuleProductPort,
    RecordIntent,
    observable,
)
from scopecat.authoring._request_values import (  # pyright: ignore[reportPrivateUsage]
    project_run_request_inputs,
)
from scopecat.authoring._resolution import (
    _link_assembly,
    compile_prepared_invocation,
    resolve_experiment,
)
from scopecat.authoring._scan_lowering import (  # pyright: ignore[reportPrivateUsage]
    lower_scan_points,
    project_scan_record,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.authoring.assembly import (
    ExperimentModule,
    ModuleInvocation,
)
from scopecat.errors import ValidationFailed
from scopecat.models.config import RoutingGraph, RoutingResource
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import (
    ParameterDefinition,
    Quantity,
    TableParameterValue,
)
from scopecat.models.run_request import RunRequest
from tests.support.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    load_config,
    simple_template,
)
from tests.support.authoring import (
    parameters as _parameters,
)
from tests.support.experiment_preview import preview_contract, preview_result


def _table_definition(
    *,
    id: str,  # noqa: A002
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


def _around_parameter_points(
    parameter_id: str = "drive_frequency",
    *,
    points: int = 5,
) -> ValueRef:
    return lower_scan_points(
        sc.axis(
            sc.point(parameter_id, _QUANTITY_VALUE),
            center=sc.parameter(parameter_id, _QUANTITY_VALUE),
            span=Quantity(value=200.0, unit="MHz"),
            points=points,
        )
    )


def _module_fixture(
    *,
    id: str,  # noqa: A002
    entity_inputs: Sequence[str] = (),
    resources: Sequence[ResourcePort] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    state_intents: Sequence[ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[RecordIntent] = (),
    product_ports: Sequence[ModuleProductPort] = (),
) -> ExperimentModule:
    return module_from_parts_internal(
        id=id,
        input_ports=tuple(
            ModuleInputPort(
                id=input_id,
                value_type=authoring.ScalarType(authoring.EntityType()),
            )
            for input_id in entity_inputs
        ),
        resources=tuple(resources),
        bindings=tuple(bindings),
        state_intents=tuple(state_intents),
        compute_nodes=tuple(compute_nodes),
        records=tuple(records),
        product_ports=tuple(product_ports),
    )


def _template_invocation(
    *modules: ExperimentModule,
    id: str,  # noqa: A002
    kind: str,
    experiment_id: str | None = None,
    inputs: Mapping[str, authoring.RuntimeInput] | None = None,
    metadata: Mapping[str, authoring.MetadataValue] | None = None,
) -> authoring.ExperimentInvocation:
    root_module = authoring.module(f"{id}.root").use(*modules).build()
    template = root_module.template(id, kind=kind)
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
    assert experiment.id == "authored-simple-scan"
    assert experiment.kind == "simple_scan"
    assert experiment.metadata == {"assembled_by": "template"}
    preview = preview_contract(experiment, resolved.parameters, config=load_config())

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
    subject = authoring.input(
        "subject",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module("test.product_module")
        .inputs(subject)
        .resource("source", requires=("set_frequency",))
        .product("signal", resource="source", unit="ratio")
        .build()
    )
    without_selection = (
        module.template("test.product_unselected", kind="product_test")
        .experiment_id("product-unselected")
        .scan(DRIVE_FREQUENCY_POINT, [4.9, 5.0, 5.1], unit="GHz")
        .build()
    )
    with_selection = (
        module.template("test.product_selected", kind="product_test")
        .experiment_id("product-selected")
        .scan(DRIVE_FREQUENCY_POINT, [4.9, 5.0, 5.1], unit="GHz")
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
        authoring.module("test.compute_provenance")
        .inputs(qubit, pulse_length)
        .resource("drive", requires=("play_pulse_program",))
        .computes(build)
        .bind(
            "drive.play_pulse_program.program",
            build.output,
        )
        .build()
    )
    template = (
        module.template("test.compute_provenance", kind="compute_provenance")
        .experiment_id("compute-provenance")
        .input(
            "pulse_length",
            default=Quantity(value=20.0, unit="ns"),
        )
        .build()
    )
    seed_config = load_config()
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
                            value_type=authoring.ScalarType(authoring.EntityType()),
                        ),
                        sc.TableColumn(
                            id="drive_frequency",
                            value_type=authoring.ScalarType(
                                authoring.QuantityType(unit="GHz")
                            ),
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
                            "qubit": EntityRef(id="q0"),
                            "drive_frequency": Quantity(value=5.0, unit="GHz"),
                        }
                    ],
                ),
            ]
        }
    )
    config = seed_config.model_copy(
        update={
            "system": seed_config.system.model_copy(
                update={"parameter_catalog": catalog}
            ),
            "parameter_snapshot": parameter_snapshot,
        }
    )

    resolved = resolve_experiment(
        template.bind(qubit="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    node = resolved.experiment.compute_nodes[0]

    assert node.inputs["qubit"].source_inputs == ["qubit"]
    assert node.inputs["length"].source_inputs == ["pulse_length"]
    assert node.inputs["frequency"].source_inputs == ["qubit"]
    assert node.output_type == authoring.ScalarType(authoring.PayloadType("pulse"))
    assert resolved.experiment.state[0].value == ComputeResultRef(
        node_id="build-program"
    )


def test_compute_rejects_raw_inputs_without_an_inferable_type() -> None:
    with pytest.raises(TypeError, match="inputs must be typed values"):
        sc.compute(
            "build-program",
            fn=lambda *, frequency: frequency,
            inputs={"frequency": param("drive_frequency")},  # type: ignore[dict-item]
            output_type=authoring.ScalarType(authoring.QuantityType()),
        )


def test_compute_function_signature_must_match_explicit_inputs() -> None:
    output_type = authoring.ScalarType(authoring.StringType())

    with pytest.raises(TypeError, match="does not match declared inputs"):
        sc.compute(
            "missing-input",
            fn=lambda *, value: value,
            output_type=output_type,
        )

    with pytest.raises(TypeError, match="must use explicit named parameters"):
        sc.compute(
            "variadic-inputs",
            fn=lambda **values: values,
            inputs={"value": "declared"},
            output_type=output_type,
        )


def test_template_can_scan_entity_input_without_subject_special_case() -> None:
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module("test.entity_scan_module")
        .inputs(qubit)
        .product("signal", resource="source", unit="ratio")
        .build()
    )
    template = (
        module.template("test.entity_scan", kind="entity_scan")
        .experiment_id("entity-scan")
        .scan(
            sc.point("qubit", authoring.ScalarType(authoring.EntityType())),
            [EntityRef(id="q0", kind="logical_device")],
        )
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview = preview_contract(resolved.experiment, resolved.parameters)

    assert preview.points[0].coordinates["qubit"] == EntityRef(
        id="q0", kind="logical_device"
    )
    assert preview.schema is not None
    coordinate = next(
        variable for variable in preview.schema.variables if variable.id == "qubit"
    )
    assert coordinate.dtype == "string"
    assert coordinate.metadata == {"entity_kind": "logical_device"}


def test_entity_scan_captures_an_immutable_durable_snapshot() -> None:
    subject = sc.point(
        "subject",
        sc.ScalarType(sc.EntityType()),
    )
    labels = ["data"]
    entity = EntityRef(id="q0", metadata={"labels": labels})

    scan = sc.axis(subject, [entity])
    labels.append("changed")
    with pytest.raises(TypeError, match="immutable"):
        entity.metadata["late"] = True  # type: ignore[index]
    request = project_scan_record(scan)

    assert request.model_dump(mode="json")["values"] == [
        {
            "kind": "entity",
            "entity_id": "q0",
            "entity_kind": None,
            "metadata": {"labels": ["data"]},
        }
    ]


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
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module("test.entity_scan_routing")
        .inputs(qubit)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind("drive.set_frequency.frequency", Quantity(value=5.0, unit="GHz"))
        .product("signal", resource="drive", unit="ratio")
        .build()
    )
    template = (
        module.template("test.entity_scan_routing", kind="entity_scan_routing")
        .experiment_id("entity-scan-routing")
        .scan(
            sc.point("qubit", authoring.ScalarType(authoring.EntityType())),
            [
                EntityRef(id="q0", kind="logical_device"),
                EntityRef(id="q1", kind="logical_device"),
            ],
        )
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
        resolved.parameters,
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
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )
    module = (
        authoring.module("test.runtime_entity_scan")
        .inputs(qubit)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind(
            "drive.set_frequency.frequency",
            authoring.parameter_lookup(
                "sample_qubits",
                key={"qubit": qubit},
                column="drive_frequency",
                value_type=authoring.ScalarType(authoring.QuantityType(unit="GHz")),
            ),
        )
        .product("signal", resource="drive", unit="ratio")
        .build()
    )
    template = (
        module.template("test.runtime_entity_scan", kind="runtime_entity_scan")
        .experiment_id("runtime-entity-scan")
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind().scan(
            sc.point(
                "qubit",
                authoring.ScalarType(
                    authoring.EntityType(entity_kind="logical_device")
                ),
            ),
            ["q0", "q1"],
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameters,
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
        authoring.module("test.runtime_entity_dependent_points")
        .inputs(qubit)
        .product("signal", unit="ratio")
        .build()
    )
    template = (
        module.template(
            "test.runtime_entity_dependent_points",
            kind="runtime_entity_dependent_points",
        )
        .experiment_id("runtime-entity-dependent-points")
        .scan(
            sc.point("drive_length", _QUANTITY_VALUE),
            center=sc.parameter_lookup(
                "sample_qubits",
                key={"qubit": qubit},
                column="rabi_length",
                value_type=_QUANTITY_VALUE,
            ),
            span=Quantity(value=20.0, unit="ns"),
            points=3,
        )
        .record_product("signal")
        .build()
    )

    resolved = resolve_experiment(
        template.bind().scan(
            sc.point(
                "qubit",
                authoring.ScalarType(
                    authoring.EntityType(entity_kind="logical_device")
                ),
            ),
            ["q0", "q1"],
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameters,
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


def test_entity_series_input_can_define_record_axis() -> None:
    qubits = sc.input(
        "qubits",
        authoring.SeriesType(authoring.ScalarType(authoring.EntityType())),
    )
    module = (
        authoring.module("test.entity_series_axis_module")
        .inputs(qubits)
        .product(
            "iq",
            resource="source",
            dtype="complex128",
            axes=(authoring.entity_axis("qubit", qubits),),
        )
        .build()
    )
    template = (
        module.template("test.entity_series_axis", kind="entity_series_axis")
        .experiment_id("entity-series-axis")
        .record_product("iq")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(qubits=("q0",)),
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

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            template.bind(qubits=("missing",)),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "unknown_authoring_entity"

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            template.bind(qubits=("q0", "q0")),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "module_record_entity_axis_duplicate"

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            template.bind(qubits=()),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "module_record_entity_axis_invalid"


def test_non_entity_string_series_defines_categorical_record_axis() -> None:
    module = (
        authoring.module("test.categorical_axis")
        .product(
            "iq",
            resource="source",
            dtype="complex128",
            axes=(
                authoring.record_axis(
                    "component",
                    size=("I", "Q"),
                    kind="component",
                ),
                authoring.record_axis(
                    "entity_role",
                    size=2,
                    kind="entity",
                ),
            ),
        )
        .build()
    )
    template = (
        module.template("test.categorical_axis", kind="categorical_axis")
        .record_product("iq")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    axis = resolved.experiment.records[0].axes[0]
    assert axis.size == 2
    assert axis.metadata == {}
    role_axis = resolved.experiment.records[0].axes[1]
    assert role_axis.kind == "entity"
    assert role_axis.size == 2
    assert role_axis.metadata == {}


def test_entity_series_routes_as_single_point_with_ordered_product_axis() -> None:
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
    qubits = sc.input(
        "qubits",
        authoring.SeriesType(authoring.ScalarType(authoring.EntityType())),
    )
    module = (
        authoring.module("test.entity_series_routing")
        .inputs(qubits)
        .resource(
            "readout",
            requires=("set_frequency",),
            for_entities=(qubits,),
        )
        .product(
            "iq",
            resource="readout",
            dtype="complex128",
            axes=(authoring.entity_axis("qubit", qubits),),
        )
        .build()
    )
    template = (
        module.template("test.entity_series_routing", kind="entity_series_routing")
        .experiment_id("entity-series-routing")
        .record_product("iq")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(qubits=("q0", "q1")),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(
        resolved.experiment,
        resolved.parameters,
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


def test_module_invocation_compiles_to_assembly_without_config() -> None:
    invocation = SIMPLE_MODULE(subject="q0")
    assembly = assemble_invocation_internal(invocation)

    assert isinstance(invocation, ModuleInvocation)
    assert isinstance(assembly, ExperimentAssemblyInternal)
    assert assembly.experiment_id is None
    assert assembly.kind is None
    assert assembly.inputs == {"subject": "q0"}
    assert assembly.resource_ports[0].id == "source"


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
        ComputeResultRef(node_id="build-program"),
    )

    for value in transient_values:
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"value": value})
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"nested": {"value": value}})


def test_link_assembly_resolves_config_dependent_fragments() -> None:
    source = assemble_invocation_internal(SIMPLE_MODULE(subject="q0"))
    points = ExperimentAssemblyInternal(point_source=_around_parameter_points())
    assembly = ExperimentAssemblyInternal.combine(
        experiment_id="authored-simple-scan",
        kind="simple_scan",
        assemblies=(points, source),
    )
    request = RunRequest(
        id="simple.request",
        template_id="test.simple_scan",
        template_inputs={"subject": "q0"},
    )

    resolved = _link_assembly(
        assembly,
        request=request,
        inputs={"subject": "q0"},
        config=load_config(),
        workspace=Path("/tmp/scopecat-test"),
        config_source=None,
    )

    assert resolved.experiment.id == "authored-simple-scan"
    assert resolved.config.id == load_config().id
    preview = preview_contract(resolved.experiment, resolved.parameters)
    assert preview.state_changes[0].resource == "source"


def test_template_composition_merges_shared_resource_port_capabilities() -> None:
    pulse = _module_fixture(
        id="test.shared_resource.pulse",
        resources=[
            resource_port("source", requires("set_frequency")),
        ],
        bindings=[
            bind(
                "source.set_frequency.frequency",
                authoring.parameter("drive_frequency", _QUANTITY_VALUE),
            )
        ],
    )
    records = _module_fixture(
        id="test.shared_resource.records",
        entity_inputs=(),
        resources=[
            resource_port("source", requires("acquire_signal")),
        ],
        records=[observable("signal", resource="source", unit="ratio")],
    )

    compiled = compile_prepared_invocation(
        prepare_invocation(
            _template_invocation(
                pulse,
                records,
                id="test.shared_resource",
                kind="simple_scan",
            )
        )
    )

    assert isinstance(compiled.assembly, ExperimentAssemblyInternal)
    assembly = compiled.assembly
    assert len(assembly.resource_ports) == 1
    assert assembly.resource_ports[0].id == "source"
    assert assembly.resource_ports[0].selector.capabilities == (
        "set_frequency",
        "acquire_signal",
    )


def test_resource_port_merge_deduplicates_only_the_same_value_handle() -> None:
    entity_type = authoring.ScalarType(authoring.EntityType())
    first = authoring.parameter("first_subject", entity_type)
    second = authoring.parameter("second_subject", entity_type)
    module = (
        authoring.module("test.shared_resource.entities")
        .resource("source", for_entities=(first,))
        .resource("source", for_entities=(second,))
        .resource("source", for_entities=(first,))
        .build()
    )

    assembly = assemble_module_internal(module)
    sources = assembly.resource_ports[0].selector.entity_inputs

    assert len(sources) == 2
    assert sources[0] is first
    assert sources[1] is second


def test_template_composition_rejects_duplicate_record_ids() -> None:
    first = _module_fixture(
        id="test.duplicate_record.first",
        resources=[
            resource_port("source", requires("set_frequency")),
        ],
        records=[observable("signal", resource="source", unit="ratio")],
    )
    second = _module_fixture(
        id="test.duplicate_record.second",
        entity_inputs=(),
        records=[observable("signal", resource="source", unit="ratio")],
    )

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            _template_invocation(
                first,
                second,
                id="test.duplicate_record",
                kind="simple_scan",
            ),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    assert error.value.diagnostics[0].code == "module_record_duplicate"


def test_module_composition_invocation_literals_bind_local_inputs() -> None:
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module("test.invocation_defaults.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind("source.set_frequency.frequency", drive_frequency)
        .build()
    )
    parent = (
        authoring.module("test.invocation_defaults.parent")
        .use(child(drive_frequency=Quantity(value=5.0, unit="GHz")))
        .build()
    )

    assembly = assemble_module_internal(
        parent,
    )

    assert "drive_frequency" not in assembly.inputs
    assert all(port.id != "drive_frequency" for port in assembly.input_ports)
    assert isinstance(assembly.bindings[0].value, ValueRef)
    first_value = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert first_value.value == Quantity(value=5.0, unit="GHz")


def test_module_invocation_rejects_undeclared_inputs() -> None:
    child = authoring.module("test.invocation_unknown_input.child").build()

    with pytest.raises(ValueError, match="received undeclared inputs: 'frequency'"):
        child(frequency=Quantity(value=5.0, unit="GHz"))


def test_module_invocation_rejects_raw_relation_inputs() -> None:
    frequency = authoring.input(
        "frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = authoring.module("test.invocation_raw_input").inputs(frequency).build()

    with pytest.raises(TypeError, match="typed values or closed literal data"):
        child(frequency=input_ref("frequency"))  # type: ignore[arg-type]


def test_module_composition_invocation_expressions_bind_local_inputs() -> None:
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module("test.invocation_override.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind("source.set_frequency.frequency", drive_frequency)
        .build()
    )
    parent = (
        authoring.module("test.invocation_expression.parent")
        .use(
            child(
                drive_frequency=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType()),
                )
            )
        )
        .build()
    )

    assembly = assemble_module_internal(
        parent,
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    assert internal_lower_value_ref(assembly.bindings[0].value) == param(
        "drive_frequency"
    )


def test_module_composition_defers_nested_expression_and_literal_bindings() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    child_value = authoring.input(
        "child_value",
        value_type,
    )
    unused_parameter = authoring.input("unused_parameter", value_type)
    unused_point = authoring.input("unused_point", value_type)
    child = (
        authoring.module("test.invocation_deferred.child")
        .inputs(child_value, unused_parameter, unused_point)
        .resource("source", requires=("set_offset",))
        .bind("source.set_offset.offset", child_value)
        .build()
    )
    parent_value = authoring.input(
        "parent_value",
        value_type,
    )
    parent = (
        authoring.module("test.invocation_deferred.parent")
        .inputs(parent_value)
        .use(
            child(
                child_value=parent_value + 0.25,
                unused_parameter=authoring.parameter(
                    "unused_parameter",
                    value_type,
                ),
                unused_point=authoring.point("unused_point", value_type),
            )
        )
        .build()
    )
    root = (
        authoring.module("test.invocation_deferred.root")
        .use(parent(parent_value=1.5))
        .build()
    )

    assembly = assemble_module_internal(root)

    assert isinstance(assembly.bindings[0].value, ValueRef)
    expression = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert expression.eval(EvalContext()) == 1.75
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
        authoring.module("test.reachable-input-provenance")
        .inputs(
            used_parameter_input,
            unused_parameter_input,
            used_point_input,
            unused_point_input,
        )
        .resource("source", requires=("set_offset", "set_gain"))
        .bind("source.set_offset.offset", used_parameter_input)
        .bind("source.set_gain.gain", used_point_input)
        .build()
    )
    used_parameter = authoring.parameter("reachable_parameter", value_type)
    unused_parameter = authoring.parameter("phantom_parameter", value_type)
    used_point = authoring.point("reachable_point", value_type)
    unused_point = authoring.point("phantom_point", value_type)

    assembly = assemble_module_internal(
        module,
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


def test_deferred_input_binding_detects_cycles_within_a_scope() -> None:
    value_type = authoring.ScalarType(authoring.FloatType())
    first = authoring.input("first", value_type)
    second = authoring.input("second", value_type)
    expression = internal_bind_value_ref_inputs(
        first + 1.0,
        {"first": second, "second": first},
    )

    with pytest.raises(ValueError, match="cyclic module input reference: first"):
        internal_lower_scalar_value_ref(expression)


def test_module_composition_invocation_input_refs_bind_to_parent_inputs() -> None:
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    outer_frequency = authoring.input(
        "outer_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module("test.invocation_parent_input.child")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency",))
        .bind("source.set_frequency.frequency", drive_frequency)
        .build()
    )
    parent = (
        authoring.module("test.invocation_parent_input.parent")
        .inputs(outer_frequency)
        .use(child(drive_frequency=outer_frequency))
        .build()
    )

    assembly = assemble_module_internal(
        parent, outer_frequency=Quantity(value=5.2, unit="GHz")
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    localized = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    assert localized.kind == "input"
    assert localized.name == "outer_frequency"


def test_module_composition_does_not_merge_sibling_invocation_inputs() -> None:
    first_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    first = (
        authoring.module("test.invocation_sibling.first")
        .inputs(first_frequency)
        .resource("source", requires=("set_frequency",))
        .bind("source.set_frequency.frequency", first_frequency)
        .build()
    )
    second_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    second = (
        authoring.module("test.invocation_sibling.second")
        .inputs(second_frequency)
        .resource("detector", requires=("set_frequency",))
        .bind(
            "detector.set_frequency.frequency",
            second_frequency,
        )
        .build()
    )

    module = (
        authoring.module("test.invocation_sibling.parent")
        .use(
            first(drive_frequency=Quantity(value=5.0, unit="GHz")),
            second(drive_frequency=Quantity(value=5.1, unit="GHz")),
        )
        .build()
    )

    assembly = assemble_module_internal(
        module,
    )

    assert "drive_frequency" not in assembly.inputs
    assert isinstance(assembly.bindings[0].value, ValueRef)
    assert isinstance(assembly.bindings[1].value, ValueRef)
    first_value = internal_lower_scalar_value_ref(assembly.bindings[0].value)
    second_value = internal_lower_scalar_value_ref(assembly.bindings[1].value)
    assert first_value.value == Quantity(value=5.0, unit="GHz")
    assert second_value.value == Quantity(value=5.1, unit="GHz")


def test_module_composition_localizes_invocation_entity_inputs() -> None:
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    drive_frequency = authoring.input(
        "drive_frequency",
        authoring.ScalarType(authoring.QuantityType()),
    )
    child = (
        authoring.module("test.invocation_entity.child")
        .inputs(qubit, drive_frequency)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind("drive.set_frequency.frequency", drive_frequency)
        .build()
    )
    parent = (
        authoring.module("test.invocation_entity.parent")
        .use(
            child(
                qubit="q0",
                drive_frequency=Quantity(value=5.0, unit="GHz"),
            )
        )
        .build()
    )

    assembly = assemble_module_internal(
        parent,
    )

    assert "qubit" not in assembly.inputs
    assert "qubit" not in assembly.entity_inputs
    assert all(port.id != "qubit" for port in assembly.input_ports)
    localized_entity = assembly.resource_ports[0].selector.entity_inputs[0]
    assert isinstance(localized_entity, ValueRef)
    assert localized_entity.value_type == authoring.ScalarType(authoring.EntityType())
    lowered_entity = internal_lower_scalar_value_ref(localized_entity)
    assert lowered_entity.kind == "literal"
    assert lowered_entity.value == EntityRef(id="q0")


def test_template_invocation_runs_composed_modules_directly() -> None:
    prelude = _module_fixture(id="test.scripted_module_prelude")
    scan = _module_fixture(
        id="test.scripted_module_scan",
        resources=[
            resource_port("source", requires("set_frequency")),
        ],
        bindings=[
            bind(
                "source.set_frequency.frequency",
                DRIVE_FREQUENCY_POINT,
            )
        ],
        records=[observable("signal", resource="source", unit="ratio")],
    )

    resolved = resolve_experiment(
        _template_invocation(
            prelude,
            scan,
            id="test.scripted_scan",
            kind="simple_scan",
        ).scan(
            DRIVE_FREQUENCY_POINT,
            center=sc.parameter("drive_frequency", _QUANTITY_VALUE),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    preview, _ = preview_result(
        resolved.experiment,
        resolved.parameters,
    )

    assert resolved.template_id == "test.scripted_scan"
    assert resolved.inputs == {}
    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.1, unit="GHz"
    )


def test_module_uses_record_axes() -> None:
    module = _module_fixture(
        id="test.record_axes",
        resources=[
            resource_port("source", requires("set_frequency")),
        ],
        bindings=[
            bind(
                "source.set_frequency.frequency",
                DRIVE_FREQUENCY_POINT,
            ),
        ],
        records=[
            observable(
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
        ).scan(
            DRIVE_FREQUENCY_POINT,
            center=sc.parameter("drive_frequency", _QUANTITY_VALUE),
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
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType()),
    )
    module = (
        authoring.module("test.entity_routed_resource")
        .inputs(qubit)
        .resource(
            "drive",
            requires=("set_frequency",),
            for_entities=(qubit,),
        )
        .bind(
            "drive.set_frequency.frequency",
            authoring.parameter(
                "drive_frequency",
                authoring.ScalarType(authoring.QuantityType(unit="GHz")),
            ),
        )
        .build()
    )

    resolved = resolve_experiment(
        (
            module.template(
                "test.entity_routed_resource",
                kind="entity_routed_resource",
            ).experiment_id("entity-routed-resource")
        ).bind(qubit="q1"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )

    preview = preview_contract(
        resolved.experiment,
        resolved.parameters,
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
            "definitions": [
                *seed_config.parameter_catalog.definitions,
                _table_definition(
                    id="flux_bias",
                    primary_key=["resource_id"],
                    columns=[
                        sc.TableColumn(
                            id="resource_id",
                            value_type=sc.ScalarType(sc.StringType()),
                        ),
                        sc.TableColumn(
                            id="offset",
                            value_type=sc.ScalarType(sc.QuantityType(unit="arb")),
                        ),
                    ],
                ),
            ]
        }
    )
    system = seed_config.system.model_copy(
        update={"parameter_catalog": catalog},
    )
    parameter_snapshot = seed_config.parameter_snapshot.model_copy(
        update={
            "values": [
                *seed_config.parameter_snapshot.values,
                TableParameterValue(
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
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )
    flux_bias = sc.parameter(
        "flux_bias",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "resource_id",
                    sc.ScalarType(sc.StringType()),
                ),
                sc.TableColumn(
                    "offset",
                    sc.ScalarType(sc.QuantityType(unit="arb")),
                ),
            )
        ),
    )
    background = (
        authoring.module("test.background_flux")
        .state_each(
            flux_bias,
            resource=lambda row: row["resource_id"],
            field="set_offset.offset",
            value=lambda row: row["offset"],
        )
        .build()
    )

    resolved = resolve_experiment(
        (
            background.template(
                "test.background_flux", kind="background_flux"
            ).experiment_id("background-flux")
        ).bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    preview = preview_contract(resolved.experiment, resolved.parameters)

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
        resolved.parameters,
        config=config,
    )

    assert diagnostics[0].code == "module_resource_port_ambiguous"


def test_resolve_experiment_uses_active_config_and_input_defaults(
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
    assert resolved.config.id == load_config().id
    assert resolved.request.config_source == "active"
    experiment = resolved.experiment
    preview = preview_contract(experiment, _parameters())

    assert preview.points[0].coordinates["drive_frequency"] == Quantity(
        value=4.9, unit="GHz"
    )
    assert preview.points[-1].coordinates["drive_frequency"] == Quantity(
        value=5.1, unit="GHz"
    )
