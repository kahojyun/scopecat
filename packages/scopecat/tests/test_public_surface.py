from __future__ import annotations

import copy
from importlib.util import find_spec
from inspect import signature
from typing import cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
import scopecat.authoring.assembly as authoring_assembly
import scopecat.models.value as value_models
import scopecat.problems as problems
import scopecat.results as results
from scopecat._relations import param


def test_raw_relation_ir_has_no_public_module() -> None:
    assert find_spec("scopecat.relations") is None


def test_internal_authoring_context_and_compute_refs_have_no_public_module() -> None:
    assert find_spec("scopecat.authoring.context") is None
    assert not hasattr(authoring, "ExperimentAuthoringContext")
    assert not hasattr(authoring, "ParameterRelationData")
    assert not hasattr(value_models, "ComputeResultRef")


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open)
    assert sc.Problem is problems.Problem
    assert callable(sc.blocking_problem)
    assert callable(sc.model_location)
    assert not hasattr(sc, "ValueValidationError")
    assert sc.Run is sc.RunHandle
    assert callable(sc.module)
    assert not hasattr(sc, "template")
    assert callable(sc.ModuleBuilder.template)
    assert callable(sc.ModuleBuilder.bind_field)
    assert not hasattr(sc.ModuleBuilder, "bind")
    assert callable(sc.ExperimentModule.template)
    assert callable(sc.Experiment.bind_field)
    assert not hasattr(sc.Experiment, "bind")
    assert sc.ModuleOutputs
    assert sc.ProductOutputs
    assert sc.ProductRef
    assert callable(sc.input)
    assert callable(sc.compute)
    assert sc.ComputeInput
    assert callable(sc.point)
    assert callable(sc.parameter)
    assert callable(sc.parameter_lookup)
    assert not hasattr(sc, "parameter_table")
    assert callable(sc.route)
    assert sc.TableRow
    assert not hasattr(sc.ValueRef, "row")
    assert not hasattr(sc.ValueRef, "source_kind")
    assert not hasattr(sc.ValueRef, "source_id")
    assert not hasattr(sc.ValueRef, "expression")
    assert not hasattr(sc.ValueRef, "parameter_contracts")
    assert not hasattr(sc.ValueRef, "input_id")
    assert not hasattr(sc.ValueRef, "node_id")
    with pytest.raises(TypeError, match="opaque handle"):
        sc.ValueRef()
    with pytest.raises(TypeError, match="callback scope"):
        sc.TableRow()
    assert sc.ResolvedRoute(
        port_id="drive",
        resource_id="drive-a",
        capabilities=("play",),
    ).capabilities == ("play",)
    assert not hasattr(sc, "var")
    assert not hasattr(sc, "param")
    assert not hasattr(sc, "table_param")
    assert not hasattr(sc, "col")
    assert not hasattr(sc, "typed")
    assert not hasattr(sc, "input_series")
    assert not hasattr(sc, "input_table")
    assert not hasattr(sc, "compute_result")
    assert not hasattr(sc, "column")
    assert not hasattr(sc, "ComputeResultRef")
    assert not hasattr(sc, "ComputeContext")
    assert not hasattr(sc, "compute_payload")
    assert not hasattr(sc, "ComputePayloadRef")
    assert sc.ScalarType(sc.IntType())
    assert sc.SeriesType(sc.ScalarType(sc.EntityType()))
    assert sc.TableType(columns=())
    assert not hasattr(sc, "EntityArray")
    assert not hasattr(sc, "entity_array")
    assert not hasattr(sc, "scan_axis_index")
    assert not hasattr(sc, "parameter_scan_records")
    assert not hasattr(sc, "PointScanRecord")
    assert not hasattr(sc, "ScanGroupRecord")
    assert sc.Scan
    assert sc.ParameterRow
    assert not hasattr(sc, "ScanAxis")
    assert not hasattr(sc, "ParameterScanAxis")
    assert not hasattr(sc, "ScanGroup")
    assert not hasattr(sc, "ScanItem")
    with pytest.raises(TypeError, match="opaque handle"):
        sc.Scan()
    with pytest.raises(TypeError, match="opaque handle"):
        sc.ParameterRow()
    with pytest.raises(TypeError, match="typed point value"):
        sc.axis("frequency", [1.0])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"created with scopecat\.point"):
        sc.axis(
            sc.input("frequency", sc.ScalarType(sc.FloatType())),
            [1.0],
        )
    for handle_type in (
        sc.Compute,
        sc.RouteRef,
        sc.ModuleBuilder,
        sc.ModuleInvocation,
        sc.ModuleOutputs,
        sc.ProductOutputs,
        sc.ProductRef,
        sc.ExperimentModule,
        sc.TemplateBuilder,
        sc.ExperimentTemplate,
        sc.ExperimentInvocation,
        sc.Experiment,
        sc.PreparedExperiment,
        sc.RecordAxis,
        sc.RecordSelection,
    ):
        with pytest.raises(TypeError, match="opaque handle"):
            handle_type()
    row = sc.param_row("parameters", entity="q0")
    assert not hasattr(row, "value")
    assert not hasattr(row, "patch")
    assert hasattr(results, "MeasurementRecord")
    assert {
        "schema_version",
        "impact",
        "category",
        "phase",
        "code",
        "location",
        "related_locations",
        "details",
        "occurrence_id",
    }.issubset(problems.Problem.model_fields)


def test_typed_values_are_the_public_module_wiring_surface() -> None:
    qubits = sc.input(
        "qubits",
        sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    program_type = sc.ScalarType(sc.PayloadType("test.program"))
    build = sc.compute(
        "build-program",
        fn=lambda qubits: tuple(qubits),
        inputs={"qubits": qubits},
        output_type=program_type,
    )

    module = sc.module("test.typed_values").inputs(qubits).computes(build).build()

    assert isinstance(module, sc.ExperimentModule)
    assert build.output.value_type == program_type

    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(sc.TableColumn("qubit", sc.ScalarType(sc.EntityType())),)
        ),
    )
    projected = rows.with_columns(lambda row: {"target": row["qubit"]})
    assert isinstance(projected.value_type, sc.TableType)
    assert [column.id for column in projected.value_type.columns] == [
        "qubit",
        "target",
    ]

    assert not hasattr(authoring, "resolve_experiment")
    assert not hasattr(authoring, "ResolvedExperiment")
    assert not hasattr(authoring, "ExperimentAuthoringContext")
    assert not hasattr(authoring, "ComputeContext")
    assert not hasattr(authoring, "param_ref")
    assert not hasattr(authoring, "var_ref")
    assert not hasattr(authoring, "typed")
    assert not hasattr(sc.ModuleInvocation, "assemble")
    assert not hasattr(sc.ModuleInvocation, "_assemble")
    assert not hasattr(sc.ExperimentModule, "assemble")
    assert not hasattr(sc.ExperimentModule, "_assemble")
    assert not hasattr(authoring_assembly, "ExperimentAssemblyInternal")
    assert not hasattr(authoring_assembly, "assemble_invocation_internal")
    assert not hasattr(authoring_assembly, "assemble_module_internal")
    assert not hasattr(authoring_assembly, "link_experiment_assembly_internal")

    public_signatures = " ".join(
        str(signature(method))
        for method in (
            sc.ModuleBuilder.bind_field,
            sc.ModuleBuilder.resource,
            sc.ModuleBuilder.state_each,
            sc.Experiment.bind_field,
            sc.Experiment.resource,
            sc.Experiment.state_each,
            sc.compute,
            sc.parameter_lookup,
            sc.ExperimentModule.__call__,
        )
    )
    assert "ScalarExpr" not in public_signatures
    assert "RelationExpr" not in public_signatures
    assert "ComputeResultRef" not in public_signatures
    assert "ResourceSelector" not in public_signatures
    assert "object" not in str(signature(sc.compute))
    assert "object" not in str(signature(sc.parameter_lookup))
    assert "object" not in str(signature(sc.ExperimentModule.__call__))
    for method in (
        sc.ExperimentTemplate.bind,
        sc.ExperimentInvocation.bind,
        sc.TemplateBuilder.bind,
        sc.PreparedExperiment.input,
        sc.PreparedExperiment.inputs,
    ):
        assert "object" not in str(signature(method))

    with pytest.raises(TypeError, match="inputs must be typed values"):
        sc.compute(
            "raw-expression",
            fn=lambda *, value: value,
            inputs={"value": param("frequency")},  # type: ignore[dict-item]
            output_type=sc.ScalarType(sc.QuantityType()),
        )
    with pytest.raises(TypeError, match="inputs must be typed values"):
        sc.compute(
            "arbitrary-object",
            fn=lambda *, value: value,
            inputs={"value": object()},  # type: ignore[dict-item]
            output_type=sc.ScalarType(sc.PayloadType("object")),
        )
    with pytest.raises(TypeError, match="typed scalar values"):
        sc.parameter_lookup(
            "parameters",
            key={"entity": param("entity")},  # type: ignore[dict-item]
            column="frequency",
            value_type=sc.ScalarType(sc.QuantityType()),
        )


def test_template_inputs_reject_arbitrary_python_objects_immediately() -> None:
    template = (
        sc.module("test.closed-runtime-input")
        .template("test.closed-runtime-input", kind="closed-runtime-input")
        .input("subject")
        .build()
    )

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="closed runtime data"):
        sc.InputDescription(id="subject", default=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=float("nan"))
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=range(3))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=memoryview(b"abc"))  # type: ignore[arg-type]


def test_public_invocations_capture_immutable_input_snapshots() -> None:
    template = (
        sc.module("test.immutable-runtime-input")
        .template("test.immutable-runtime-input", kind="immutable-runtime-input")
        .input("settings")
        .build()
    )
    labels = ["q0"]
    settings = cast("sc.RuntimeInput", {"labels": labels})

    invocation = template.bind(settings=settings)
    labels.append("q1")
    cast("dict[str, object]", settings)["mode"] = "changed"

    captured = cast("dict[str, object]", invocation.inputs["settings"])
    assert captured == {"labels": ("q0",)}
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", invocation.inputs)["settings"] = {}
    with pytest.raises(TypeError, match="immutable"):
        captured["mode"] = "changed"
    with pytest.raises(TypeError):
        dict.__setitem__(invocation.inputs, "settings", object())  # type: ignore[arg-type]

    labels_metadata = ["data"]
    entity = sc.EntityRef(id="q0", metadata={"labels": labels_metadata})
    entity_invocation = template.bind(settings=entity)
    labels_metadata.append("changed")
    with pytest.raises(TypeError, match="immutable"):
        entity.metadata["late"] = True  # type: ignore[index]

    captured_entity = cast("sc.EntityRef", entity_invocation.inputs["settings"])
    assert captured_entity.metadata == {"labels": ("data",)}
    assert captured_entity.model_dump(mode="json")["metadata"] == {"labels": ["data"]}
    assert copy.deepcopy(captured_entity) == captured_entity
    assert captured_entity.model_copy(deep=True) == captured_entity

    payload = sc.input(
        "payload",
        sc.ScalarType(sc.PayloadType("test.payload")),
    )
    module = sc.module("test.immutable-module-input").inputs(payload).build()
    items = [1]
    module_invocation = module(payload=cast("sc.ModuleInput", {"items": items}))
    items.append(2)

    assert module_invocation.inputs["payload"] == {"items": (1,)}
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", module_invocation.inputs)["payload"] = {}

    with pytest.raises(ValueError, match="durable JSON"):
        sc.module("test.bad-record-metadata").record(
            "signal",
            metadata={"callback": object()},  # type: ignore[dict-item]
        )


def test_typed_around_scans_reject_incompatible_quantity_dimensions() -> None:
    frequency = sc.point(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    duration = sc.point(
        "duration",
        sc.ScalarType(sc.QuantityType(unit="ns")),
    )

    with pytest.raises(TypeError, match="scan point quantity type"):
        sc.axis(frequency, center=duration, span="20 MHz", points=3)
    with pytest.raises(TypeError, match="incompatible with point dimension"):
        sc.axis(
            frequency, center=sc.Quantity(value=5.0, unit="GHz"), span="20 ns", points=3
        )


def test_routes_capture_and_validate_capabilities() -> None:
    capabilities = ["play"]

    route = sc.route("drive", capabilities=capabilities)
    capabilities.append("late")

    assert route.value_type.capabilities == ("play",)
    with pytest.raises(TypeError, match="non-empty strings"):
        sc.route("drive", capabilities=[""])
    with pytest.raises(TypeError, match="non-empty strings"):
        sc.route("drive", capabilities="play")


def test_scans_reject_non_finite_durable_values_at_capture() -> None:
    floating = sc.point(
        "floating",
        sc.ScalarType(sc.FloatType(finite=False)),
    )
    frequency = sc.point(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz", finite=False)),
    )

    with pytest.raises(ValueError, match="finite"):
        sc.axis(floating, [float("nan")])
    with pytest.raises(ValueError, match="finite"):
        sc.axis(
            frequency,
            [sc.Quantity(value=float("inf"), unit="GHz")],
        )
    with pytest.raises(ValueError, match="finite"):
        sc.axis(
            frequency,
            center=sc.Quantity(value=5.0, unit="GHz"),
            span=sc.Quantity(value=float("inf"), unit="GHz"),
            points=3,
        )


def test_workspace_terminals_are_prepare_or_scratch_only() -> None:
    assert callable(sc.Workspace.prepare)
    assert callable(sc.Workspace.experiment)

    assert callable(sc.PreparedExperiment.run)
    assert callable(sc.PreparedExperiment.preview)
    assert callable(sc.PreparedExperiment.validate)
    assert not hasattr(sc.PreparedExperiment, "prepared_invocation")
    assert not hasattr(sc.PreparedExperiment, "run_options")
    assert not hasattr(sc.RunHandle, "preview")
    assert callable(sc.Experiment.run)
    assert callable(sc.Experiment.preview)
    assert callable(sc.Experiment.validate)
