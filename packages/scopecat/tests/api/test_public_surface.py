from __future__ import annotations

import copy
from typing import Annotated, cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
import scopecat.daemon as daemon
import scopecat.kernel.payloads as value_models
import scopecat.measurements.results as results
import scopecat.sdk.problems as problems
from scopecat.authoring._value_refs import internal_lower_scalar_value_ref
from scopecat.compiler.relations.context import EvalContext
from tests.testkit.relation_plans import evaluate_scalar


def _identity_entity(qubit: str) -> str:
    return qubit


def test_root_lazy_exports_are_complete_visible_and_resolvable() -> None:
    assert len(sc.__all__) == len(set(sc.__all__))
    assert set(sc.__all__) <= set(dir(sc))

    for name in sc.__all__:
        assert getattr(sc, name) is not None


def test_daemon_package_does_not_reexport_transport_contracts() -> None:
    assert daemon.__all__ == []


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open_project)
    assert problems.Problem
    assert callable(problems.problem)
    assert callable(problems.model_location)
    assert callable(sc.module)
    assert callable(sc.template)
    assert callable(sc.scratch)
    assert sc.ExperimentModule
    assert sc.ExperimentTemplate
    assert sc.ScratchDefinition
    assert callable(sc.ModuleBuilder.bind_property)
    assert callable(sc.ExperimentBody.record_product)
    assert callable(sc.ExperimentBody.record_coordinate)
    assert callable(sc.record_coordinate)
    assert sc.ModuleOutputs
    assert sc.ProductOutputs
    assert sc.ProductRef
    assert callable(sc.input)
    assert callable(sc.compute)
    assert sc.ComputeInput
    assert callable(sc.coordinate)
    assert callable(sc.parameter)
    assert callable(sc.parameter_lookup)
    assert sc.ScalarType(sc.IntType())
    assert sc.TableType(columns=())
    assert sc.Scan
    assert hasattr(results, "MeasurementRecord")
    assert {
        "phase",
        "code",
        "location",
        "related_locations",
        "details",
        "occurrence_id",
    }.issubset(problems.Problem.model_fields)


def test_experiment_modules_are_closed_by_authoring_entry_points() -> None:
    with pytest.raises(TypeError, match=r"@module or ModuleBuilder\.build"):
        sc.ExperimentModule()


def test_module_invocations_are_closed_by_their_definition_handles() -> None:
    with pytest.raises(TypeError, match="calling or instantiating a module"):
        sc.ModuleInvocation()


def test_typed_values_are_the_public_module_wiring_surface() -> None:
    qubit_type = sc.ScalarType(sc.EntityType())
    qubit = sc.input(
        "qubit",
        qubit_type,
    )
    build = sc.compute(
        "select-qubit",
        fn=_identity_entity,
        inputs={"qubit": qubit},
        output_type=qubit_type,
    )

    module = (
        sc.module_body(id="test.typed_values").inputs(qubit).computes(build).build()
    )

    assert isinstance(module, sc.ExperimentModule)
    assert build.output.value_type == qubit_type

    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(sc.TableColumn("qubit", sc.ScalarType(sc.EntityType())),)
        ),
    )
    assert isinstance(rows.value_type, sc.TableType)


def test_experiment_inputs_reject_non_finite_numbers() -> None:
    @sc.template(
        id="test.closed-runtime-input",
        kind="closed-runtime-input",
    )
    def template(subject: float) -> sc.ExperimentBody:
        del subject
        return sc.experiment()

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=float("nan"))


def test_public_invocations_capture_immutable_input_snapshots() -> None:
    @sc.template(
        id="test.immutable-runtime-input",
        kind="immutable-runtime-input",
    )
    def template(
        settings: Annotated[dict[str, object], sc.PayloadType("test.settings")],
    ) -> sc.ExperimentBody:
        del settings
        return sc.experiment()

    labels = ["q0"]
    nested_settings: dict[str, object] = {"labels": labels}
    settings: dict[str, object] = {"nested": nested_settings}

    invocation = template.bind(settings=settings)
    labels.append("q1")
    nested_settings["mode"] = "changed"
    settings["other"] = "changed"

    captured = cast("dict[str, object]", invocation.inputs["settings"])
    assert captured == {"nested": {"labels": ("q0",)}}

    labels_metadata = ["data"]
    entity = sc.EntityRef(id="q0", metadata={"labels": labels_metadata})

    @sc.template(id="test.immutable-entity", kind="immutable-entity")
    def entity_template(
        settings: Annotated[sc.EntityRef | str, sc.EntityType()],
    ) -> sc.ExperimentBody:
        del settings
        return sc.experiment()

    entity_invocation = entity_template.bind(settings=entity)
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
    module = sc.module_body(id="test.immutable-module-input").inputs(payload).build()
    items = [1]
    nested_payload: dict[str, object] = {"items": items}
    payload_source: dict[str, object] = {"nested": nested_payload}
    module_invocation = module.instantiate(
        "immutable-input",
        payload=cast("authoring.ModuleInput", payload_source),
    )
    items.append(2)
    nested_payload["mode"] = "changed"
    payload_source["other"] = "changed"

    captured_payload = evaluate_scalar(
        internal_lower_scalar_value_ref(module_invocation.inputs["payload"]),
        EvalContext(),
    )
    assert isinstance(captured_payload, value_models.PayloadValue)
    assert captured_payload.payload == {"nested": {"items": (1,)}}


def test_public_input_boundaries_reject_invalid_recursive_values() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    default_items = ["initial"]
    default_nested: dict[str, object] = {"items": default_items}
    default_settings: dict[str, object] = {"nested": default_nested}

    @sc.template(
        id="test.recursive-runtime-input",
        kind="recursive-runtime-input",
    )
    def template(
        settings: Annotated[
            dict[str, object], sc.PayloadType("test.settings")
        ] = default_settings,
    ) -> sc.ExperimentBody:
        del settings
        return sc.experiment()

    default_items.append("changed")
    default_nested["mode"] = "changed"
    assert template.definition.inputs[0].default == {"nested": {"items": ("initial",)}}

    cyclic_default = cyclic
    with pytest.raises(TypeError, match="closed runtime data"):

        @sc.template
        def invalid_default(  # pyright: ignore[reportUnusedFunction]
            settings: Annotated[
                dict[str, object], sc.PayloadType("test.settings")
            ] = cyclic_default,
        ) -> sc.ExperimentBody:
            del settings
            return sc.experiment()

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(settings=cyclic)
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(settings={"nested": {"number": float("inf")}})
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(
            settings=cast("dict[str, object]", {"nested": {1: "invalid"}}),
        )

    payload = sc.input(
        "payload",
        sc.ScalarType(sc.PayloadType("test.payload")),
    )
    module = sc.module_body(id="test.recursive-module-input").inputs(payload).build()
    with pytest.raises(TypeError, match="typed values or closed literal data"):
        module.instantiate(
            "cyclic",
            payload=cast("authoring.ModuleInput", cyclic),
        )
    with pytest.raises(TypeError, match="typed values or closed literal data"):
        module.instantiate(
            "non-finite",
            payload=cast(
                "authoring.ModuleInput",
                {"nested": {"number": float("inf")}},
            ),
        )


def test_typed_around_scans_reject_incompatible_quantity_dimensions() -> None:
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    duration = sc.coordinate(
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
    floating = sc.coordinate(
        "floating",
        sc.ScalarType(sc.FloatType(finite=False)),
    )
    frequency = sc.coordinate(
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
