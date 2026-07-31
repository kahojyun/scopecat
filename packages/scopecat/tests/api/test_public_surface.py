from __future__ import annotations

import copy
from typing import Annotated, cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
import scopecat.kernel.payloads as value_models
from scopecat.compiler.relations.context import EvalContext
from scopecat.program.value_refs import internal_lower_scalar_value_ref
from tests.testkit.expressions import evaluate_scalar


def _identity_entity(qubit: str) -> str:
    return qubit


def test_root_lazy_exports_are_complete_visible_and_resolvable() -> None:
    assert len(sc.__all__) == len(set(sc.__all__))
    assert set(sc.__all__) <= set(dir(sc))

    for name in sc.__all__:
        assert getattr(sc, name) is not None


def test_experiment_modules_are_closed_by_authoring_entry_points() -> None:
    with pytest.raises(TypeError, match="@module"):
        sc.ExperimentModule()


def test_module_invocations_are_closed_by_their_definition_handles() -> None:
    with pytest.raises(TypeError, match="calling or instantiating a module"):
        sc.ModuleInvocation()


def test_typed_values_are_the_public_module_wiring_surface() -> None:
    qubit_type = sc.ScalarType(sc.EntityType())

    @sc.module(id="test.typed-values")
    def typed_values(
        module: sc.ModuleContext,
        qubit: Annotated[
            sc.Input[sc.EntityRef | str],
            sc.ScalarType(sc.EntityType()),
        ],
    ) -> None:
        module.compute(
            "select-qubit",
            fn=_identity_entity,
            inputs={"qubit": qubit},
            output_type=qubit_type,
        )

    assert isinstance(typed_values, sc.ExperimentModule)
    assert typed_values.operations[0].output_type == qubit_type


def test_experiment_inputs_reject_non_finite_numbers() -> None:
    @sc.template(
        id="test.closed-runtime-input",
        kind="closed-runtime-input",
    )
    def template(experiment: sc.ExperimentContext, subject: float) -> None:
        del experiment, subject

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(subject=float("nan"))


def test_public_invocations_capture_immutable_input_snapshots() -> None:
    @sc.template(
        id="test.immutable-runtime-input",
        kind="immutable-runtime-input",
    )
    def template(
        experiment: sc.ExperimentContext,
        settings: Annotated[dict[str, object], sc.PayloadType("test.settings")],
    ) -> None:
        del experiment, settings

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
        experiment: sc.ExperimentContext,
        settings: Annotated[sc.EntityRef | str, sc.EntityType()],
    ) -> None:
        del experiment, settings

    entity_invocation = entity_template.bind(settings=entity)
    labels_metadata.append("changed")

    captured_entity = cast("sc.EntityRef", entity_invocation.inputs["settings"])
    assert captured_entity.metadata == {"labels": ("data",)}
    assert captured_entity.model_dump(mode="json")["metadata"] == {"labels": ["data"]}
    assert copy.deepcopy(captured_entity) == captured_entity
    assert captured_entity.model_copy(deep=True) == captured_entity

    @sc.module(id="test.immutable-module-input")
    def payload_module(
        module: sc.ModuleContext,
        payload: Annotated[
            sc.Input[dict[str, object]],
            sc.PayloadType("test.payload"),
        ],
    ) -> None:
        del module, payload

    items = [1]
    nested_payload: dict[str, object] = {"items": items}
    payload_source: dict[str, object] = {"nested": nested_payload}
    module_invocation = payload_module.instantiate(
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
        experiment: sc.ExperimentContext,
        settings: Annotated[
            dict[str, object], sc.PayloadType("test.settings")
        ] = default_settings,
    ) -> None:
        del experiment, settings

    default_items.append("changed")
    default_nested["mode"] = "changed"
    assert template.definition.inputs[0].default == {"nested": {"items": ("initial",)}}

    cyclic_default = cyclic
    with pytest.raises(TypeError, match="closed runtime data"):

        @sc.template
        def invalid_default(  # pyright: ignore[reportUnusedFunction]
            experiment: sc.ExperimentContext,
            settings: Annotated[
                dict[str, object], sc.PayloadType("test.settings")
            ] = cyclic_default,
        ) -> None:
            del experiment, settings

    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(settings=cyclic)
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(settings={"nested": {"number": float("inf")}})
    with pytest.raises(TypeError, match="closed runtime data"):
        template.bind(
            settings=cast("dict[str, object]", {"nested": {1: "invalid"}}),
        )

    @sc.module(id="test.recursive-module-input")
    def payload_module(
        module: sc.ModuleContext,
        payload: Annotated[
            sc.Input[dict[str, object]],
            sc.PayloadType("test.payload"),
        ],
    ) -> None:
        del module, payload

    with pytest.raises(TypeError, match="typed values or closed literal data"):
        payload_module.instantiate(
            "cyclic",
            payload=cast("authoring.ModuleInput", cyclic),
        )
    with pytest.raises(TypeError, match="typed values or closed literal data"):
        payload_module.instantiate(
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
