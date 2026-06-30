"""Readout experiment authoring templates."""

from __future__ import annotations

import scopecat.authoring as authoring
from scopecat.authoring import (
    AroundSweep,
    ExperimentDraft,
    ExperimentTemplate,
    TemplateRegistry,
)
from scopecat.errors import ValidationFailed
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription

READOUT_FREQUENCY_TEMPLATE_ID = "quantum_lab_demo.readout.frequency_calibration"
READOUT_IQ_QUALITY_TEMPLATE_ID = "quantum_lab_demo.readout.iq_quality"


def frequency_calibration(
    *,
    qubit: str,
    sweep: AroundSweep | None = None,
) -> ExperimentDraft:
    return READOUT_FREQUENCY_TEMPLATE(qubit=qubit, sweep=sweep)


def iq_quality(*, qubit: str) -> ExperimentDraft:
    return READOUT_IQ_QUALITY_TEMPLATE(qubit=qubit)


def register_templates(
    template_registry: TemplateRegistry | None = None,
) -> tuple[ExperimentTemplate, ExperimentTemplate]:
    selected = template_registry or authoring.registry()
    registered: list[ExperimentTemplate] = []
    for experiment_template in (
        READOUT_FREQUENCY_TEMPLATE,
        READOUT_IQ_QUALITY_TEMPLATE,
    ):
        try:
            registered.append(selected.register(experiment_template))
        except ValidationFailed as error:
            if error.diagnostics[0].code != "experiment_template_duplicate":
                raise
            registered.append(selected.get(experiment_template.id))
    return registered[0], registered[1]


READOUT_FREQUENCY_RECIPE = authoring.recipe(
    id=READOUT_FREQUENCY_TEMPLATE_ID,
    experiment_id="sample-readout-frequency-calibration-s21",
    kind="readout_frequency_calibration",
    subject_inputs=("qubit",),
    resources=[
        authoring.resource_role(
            "readout",
            authoring.requires("readout_pulse", "demodulate_iq", "capture_dataset"),
        ),
        authoring.resource_role("flux_bias", authoring.requires("set_offset")),
    ],
    variables=[
        authoring.sweep(
            "readout_frequency",
            default_span=Quantity(value=100.0, unit="MHz"),
            points=101,
        ),
        authoring.derive(
            "lo_frequency",
            authoring.var_ref("readout_frequency")
            - authoring.param_ref("demod_frequency"),
        ),
    ],
    bindings=[
        authoring.bind(
            "readout.readout_pulse.frequency",
            authoring.var_ref("readout_frequency"),
        ),
        authoring.bind(
            "readout.readout_pulse.power",
            authoring.param_ref("readout_power"),
        ),
        authoring.bind(
            "readout.readout_pulse.phase",
            authoring.param_ref("readout_phase"),
        ),
        authoring.bind(
            "readout.demodulate_iq.lo_frequency",
            authoring.var_ref("lo_frequency"),
        ),
        authoring.bind(
            "readout.demodulate_iq.demod_frequency",
            authoring.param_ref("demod_frequency"),
        ),
        authoring.bind(
            "readout.capture_dataset.start_delay",
            authoring.param_ref("start_delay"),
        ),
        authoring.bind(
            "readout.capture_dataset.repetitions",
            authoring.param_ref("repetitions"),
        ),
        authoring.bind(
            "flux_bias.set_offset.offset",
            authoring.param_ref("readout_z_offset"),
        ),
    ],
    acquisition=authoring.acquisition(
        "iq",
        repetitions=authoring.param_ref("repetitions"),
    ),
    dataset=authoring.point_dataset(
        coordinates=[authoring.coordinate("readout_frequency")],
        observables=[authoring.observable("raw_i"), authoring.observable("raw_q")],
    ),
    metadata={
        "source_sample": "synthetic S21 scan",
        "source_function": "readout frequency response",
        "migration_scope": "single-axis readout-frequency scan",
        "template_id": READOUT_FREQUENCY_TEMPLATE_ID,
    },
)

READOUT_IQ_QUALITY_RECIPE = authoring.recipe(
    id=READOUT_IQ_QUALITY_TEMPLATE_ID,
    experiment_id="sample-readout-iq-scatter",
    kind="readout_iq_scatter",
    subject_inputs=("qubit",),
    resources=[
        authoring.resource_role(
            "readout",
            authoring.requires("readout_pulse", "capture_shots"),
        ),
    ],
    bindings=[
        authoring.bind(
            "readout.readout_pulse.frequency",
            authoring.param_ref("readout_frequency"),
        ),
        authoring.bind(
            "readout.readout_pulse.power",
            authoring.param_ref("readout_power"),
        ),
        authoring.bind(
            "readout.capture_shots.shots",
            authoring.param_ref("repetitions"),
        ),
    ],
    acquisition=authoring.acquisition(
        "iq",
        shots=authoring.param_ref("repetitions"),
        record="shot",
    ),
    dataset=authoring.shot_dataset(
        count_parameter_id="repetitions",
        observables=[
            authoring.observable("i0"),
            authoring.observable("q0"),
            authoring.observable("i1"),
            authoring.observable("q1"),
        ],
    ),
    metadata={
        "source_sample": "synthetic IQ scatter",
        "source_function": "readout IQ scatter",
        "migration_scope": "shot-level two-state readout IQ quality",
        "template_id": READOUT_IQ_QUALITY_TEMPLATE_ID,
    },
)


READOUT_FREQUENCY_TEMPLATE = READOUT_FREQUENCY_RECIPE.template(
    label="Readout frequency calibration",
    description="Build the readout frequency calibration experiment.",
    inputs=(
        ProviderOptionDescription(
            id="qubit",
            dtype="str",
            required=True,
            label="Qubit",
        ),
        ProviderOptionDescription(
            id="sweep",
            dtype="AroundSweep | None",
            default=None,
            label="Sweep",
        ),
    ),
    metadata={"category": "readout_frequency"},
)

READOUT_IQ_QUALITY_TEMPLATE = READOUT_IQ_QUALITY_RECIPE.template(
    label="Readout IQ quality",
    description="Build the shot-level readout IQ quality experiment.",
    inputs=(
        ProviderOptionDescription(
            id="qubit",
            dtype="str",
            required=True,
            label="Qubit",
        ),
    ),
    metadata={"category": "readout_iq_quality"},
)


__all__ = [
    "READOUT_FREQUENCY_TEMPLATE",
    "READOUT_FREQUENCY_TEMPLATE_ID",
    "READOUT_IQ_QUALITY_TEMPLATE",
    "READOUT_IQ_QUALITY_TEMPLATE_ID",
    "frequency_calibration",
    "iq_quality",
    "register_templates",
]
