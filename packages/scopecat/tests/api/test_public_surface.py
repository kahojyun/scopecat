from __future__ import annotations

import copy
from pathlib import Path
from typing import cast

import pytest

import scopecat as sc
import scopecat.kernel.payloads as value_models
import scopecat.kernel.problems as problems
import scopecat.measurements.results as results
from scopecat.authoring._value_refs import internal_lower_scalar_value_ref
from scopecat.compiler.relations.evaluation import EvalContext
from tests.testkit.relation_plans import evaluate_scalar


def _tuple_entities(qubits: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(qubits)


def test_root_lazy_exports_are_complete_visible_and_resolvable() -> None:
    assert len(sc.__all__) == len(set(sc.__all__))
    assert set(sc.__all__) <= set(dir(sc))

    for name in sc.__all__:
        assert getattr(sc, name) is not None


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open)
    assert sc.Problem is problems.Problem
    assert callable(sc.blocking_problem)
    assert callable(sc.model_location)
    assert sc.Run is sc.RunHandle
    assert callable(sc.module)
    assert callable(sc.ModuleBuilder.template)
    assert callable(sc.ModuleBuilder.bind_field)
    assert callable(sc.ExperimentModule.template)
    assert callable(sc.Experiment.bind_field)
    assert sc.ModuleOutputs
    assert sc.ProductOutputs
    assert sc.ProductRef
    assert callable(sc.input)
    assert callable(sc.compute)
    assert sc.ComputeInput
    assert callable(sc.point)
    assert callable(sc.parameter)
    assert callable(sc.parameter_lookup)
    assert sc.TableRow
    assert sc.ScalarType(sc.IntType())
    assert sc.SeriesType(sc.ScalarType(sc.EntityType()))
    assert sc.TableType(columns=())
    assert sc.Scan
    assert sc.ParameterRow
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


def test_workspace_is_compared_by_session_identity(tmp_path: Path) -> None:
    first = sc.open(tmp_path)
    second = sc.open(tmp_path)

    assert first is not second
    assert first != second
    assert copy.copy(first) is first
    assert copy.deepcopy(first) is first


def test_typed_values_are_the_public_module_wiring_surface() -> None:
    qubits = sc.input(
        "qubits",
        sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    program_type = sc.ScalarType(sc.PayloadType("test.program"))
    build = sc.compute(
        "build-program",
        fn=_tuple_entities,
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
    callback_rows: list[sc.TableRow] = []

    def add_target(row: sc.TableRow) -> dict[str, sc.ValueRef]:
        callback_rows.append(row)
        return {"target": row["qubit"]}

    projected = rows.with_columns(add_target)
    assert isinstance(projected.value_type, sc.TableType)
    assert [column.id for column in projected.value_type.columns] == [
        "qubit",
        "target",
    ]


def test_template_inputs_reject_non_finite_numbers() -> None:
    template = (
        sc.module("test.closed-runtime-input")
        .template("test.closed-runtime-input", kind="closed-runtime-input")
        .input("subject")
        .build()
    )

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=float("nan"))


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

    labels_metadata = ["data"]
    entity = sc.EntityRef(id="q0", metadata={"labels": labels_metadata})
    entity_invocation = template.bind(settings=entity)
    labels_metadata.append("changed")

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
    module_invocation = module.instantiate(
        "immutable-input",
        payload=cast("sc.ModuleInput", {"items": items}),
    )
    items.append(2)

    captured_payload = evaluate_scalar(
        internal_lower_scalar_value_ref(module_invocation.inputs["payload"]),
        EvalContext(),
    )
    assert isinstance(captured_payload, value_models.PayloadValue)
    assert captured_payload.payload == {"items": (1,)}


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
    assert callable(sc.PreparedExperiment.check)
    assert callable(sc.Experiment.run)
    assert callable(sc.Experiment.preview)
    assert callable(sc.Experiment.check)
