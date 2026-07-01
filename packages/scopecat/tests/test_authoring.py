from __future__ import annotations

from pathlib import Path

import pytest

import scopecat.authoring as authoring
from scopecat.authoring import (
    TemplateRegistry,
    resolve_experiment,
)
from scopecat.authoring.expressions import opaque_asset
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, plan_experiment
from scopecat.models.parameter import Quantity
from scopecat.workflows import register_and_activate_config_profile
from tests.support.authoring import (
    SIMPLE_RECIPE,
    custom_asset_recipe,
    load_config,
    simple_template,
)
from tests.support.authoring import (
    parameter_build as _parameter_build,
)


def test_template_registry_registers_lists_builds_and_rejects_duplicates() -> None:
    registry = TemplateRegistry()
    experiment_template = simple_template()

    registry.register(experiment_template)
    draft = registry.build("test.simple_scan", subject="q0")

    assert registry.get("test.simple_scan") is experiment_template
    assert registry.list() == (experiment_template,)
    assert draft.template is experiment_template
    assert draft.inputs["subject"] == "q0"
    with pytest.raises(ValidationFailed) as error:
        registry.register(experiment_template)
    assert error.value.diagnostics[0].code == "experiment_template_duplicate"


def test_recipe_draft_resolves_roles_sweeps_bindings_and_metadata() -> None:
    resolved = resolve_experiment(
        SIMPLE_RECIPE(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert resolved.template_id is None
    experiment = resolved.experiment
    assert isinstance(experiment, ExperimentSpec)
    assert experiment.id == "authored-simple-scan"
    assert experiment.kind == "simple_scan"
    assert experiment.metadata == {"assembled_by": "recipe"}
    plan = plan_experiment(experiment, _parameter_build())

    assert plan.point_coordinate_ids == ["drive_frequency"]
    assert plan.points[0].row["drive_frequency"] == Quantity(value=4.9, unit="GHz")
    assert experiment.acquire.kind == "measurement"
    assert plan.desired_state[0].resource == "source-0"
    assert plan.desired_state[0].field == "set_frequency.frequency"
    assert plan.desired_state[0].value == Quantity(value=4.9, unit="GHz")


def test_short_authoring_helpers_lower_to_plan() -> None:
    recipe = authoring.recipe(
        id="test.short_helpers",
        experiment_id="short-helper-scan",
        kind="simple_scan",
        resources=[
            authoring.resource_role("source", authoring.requires("set_frequency")),
        ],
        variables=[
            authoring.sweep(
                "drive_frequency",
                default_span=Quantity(value=200.0, unit="MHz"),
                points=5,
            ),
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
        dataset=authoring.point_dataset(
            coordinates=[authoring.coordinate("drive_frequency")],
            observables=[authoring.observable("signal")],
        ),
    )

    resolved = resolve_experiment(
        recipe(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    plan = plan_experiment(resolved.experiment, _parameter_build())

    assert resolved.experiment.id == "short-helper-scan"
    assert plan.point_coordinate_ids == ["drive_frequency", "drive_detuning"]
    assert plan.desired_state[0].field == "set_frequency.frequency"


def test_recipe_uses_generic_acquisition_helper() -> None:
    recipe = authoring.recipe(
        id="test.generic_acquisition",
        experiment_id="generic-acquisition-scan",
        kind="simple_scan",
        resources=[
            authoring.resource_role("source", authoring.requires("set_frequency")),
        ],
        variables=[
            authoring.sweep(
                "drive_frequency",
                default_span=Quantity(value=200.0, unit="MHz"),
                points=5,
            )
        ],
        bindings=[
            authoring.bind(
                "source.set_frequency.frequency",
                authoring.var_ref("drive_frequency"),
            ),
        ],
        acquisition=authoring.acquisition(
            "scalar",
            shots=2,
            repetitions=3,
            record="shot",
        ),
    )

    resolved = resolve_experiment(
        recipe(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert resolved.experiment.acquire.kind == "scalar"
    assert resolved.experiment.acquire.shots == 2
    assert resolved.experiment.acquire.repetitions == 3
    assert resolved.experiment.acquire.record == "shot"


def test_recipe_draft_resolves_multiple_subject_inputs() -> None:
    recipe = authoring.recipe(
        id="test.multi_subject",
        experiment_id="authored-multi-subject",
        kind="multi_subject",
        subject_inputs=("device", "drive_channel"),
    )

    resolved = resolve_experiment(
        recipe(device="q0", drive_channel="drive-q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert resolved.experiment.id == "authored-multi-subject"


def test_recipe_assembler_reports_ambiguous_resource_role() -> None:
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
            )
        }
    )
    config = seed_config.model_copy(update={"system": system})

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            SIMPLE_RECIPE(subject="q0"),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=config,
        )

    assert error.value.diagnostics[0].code == "recipe_resource_role_ambiguous"


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
    draft = simple_template()(subject="q0")

    resolved = resolve_experiment(draft, workspace=tmp_path)

    assert resolved.template_id == "test.simple_scan"
    assert resolved.config_provenance is not None
    assert resolved.config_provenance.entry_id == "seed"
    experiment = resolved.experiment
    assert isinstance(experiment, ExperimentSpec)
    plan = plan_experiment(experiment, _parameter_build())

    assert plan.points[0].row["drive_frequency"] == Quantity(value=4.9, unit="GHz")
    assert plan.points[-1].row["drive_frequency"] == Quantity(value=5.1, unit="GHz")


def test_opaque_asset_binding_is_preserved_in_experiment_and_plan() -> None:
    program = opaque_asset(
        id="custom-pulse-program",
        kind="pulse_program",
        media_type="text/x-python",
    )
    resolved = resolve_experiment(
        custom_asset_recipe(program)(subject="q0"),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    experiment = resolved.experiment
    assert isinstance(experiment, ExperimentSpec)

    plan = plan_experiment(experiment, _parameter_build())

    assert experiment.assets[0].id == program.id
    assert experiment.assets[0].kind == program.kind
    assert plan.desired_state[0].field == "set_frequency.program"
    assert plan.desired_state[0].value == {
        "kind": "asset",
        "asset_id": "custom-pulse-program",
    }
