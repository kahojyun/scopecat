"""Sample-backed authoring templates."""

from __future__ import annotations

from collections.abc import Sequence

import scopecat.authoring as authoring
from scopecat.authoring import (
    AroundSweep,
    ExperimentAuthoringContext,
    ExperimentDraft,
    ExperimentTemplate,
    TemplateRegistry,
)
from scopecat.authoring.expressions import (
    ExperimentVariable,
    points,
)
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, acquire, observe, set_state
from scopecat.models.artifact import ExperimentAsset
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.relations import RelationExpr, col, grid, linspace, param, values

TableVariable = tuple[str, str, str | None]


def _asset(
    *,
    id: str,  # noqa: A002
    kind: str,
    media_type: str,
) -> ExperimentAsset:
    return ExperimentAsset(
        id=id,
        kind=kind,
        uri=f"scopecat-asset:{id}",
        media_type=media_type,
    )


def _table_var(id: str, label: str, unit: str | None = None) -> TableVariable:  # noqa: A002
    return id, label, unit


RABI_TEMPLATE_ID = "quantum_lab_demo.sample.rabi"
READOUT_TEMPLATE_ID = "quantum_lab_demo.sample.readout_frequency"
SQG_RB_TEMPLATE_ID = "quantum_lab_demo.sample.sqg_rb"
CZ_RB_TEMPLATE_ID = "quantum_lab_demo.sample.cz_rb"


def rabi(
    *,
    qubit: str,
    sweep: AroundSweep | None = None,
) -> ExperimentDraft:
    return RABI_TEMPLATE(qubit=qubit, sweep=sweep)


def readout_frequency(
    *,
    qubit: str,
    sweep: AroundSweep | None = None,
) -> ExperimentDraft:
    return READOUT_TEMPLATE(qubit=qubit, sweep=sweep)


def sqg_rb(
    *,
    qubit: str,
    lengths: Sequence[int] | None = None,
    seed: int = 0,
) -> ExperimentDraft:
    return SQG_RB_TEMPLATE(qubit=qubit, lengths=lengths, seed=seed)


def cz_rb(
    *,
    control_qubit: str,
    partner_qubit: str,
    coupler: str = "coupler-q0-q1",
    lengths: Sequence[int] | None = None,
    seed: int = 0,
    interleaved_gate: str = "CZ",
) -> ExperimentDraft:
    return CZ_RB_TEMPLATE(
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        coupler=coupler,
        lengths=lengths,
        seed=seed,
        interleaved_gate=interleaved_gate,
    )


def register_templates(
    template_registry: TemplateRegistry | None = None,
) -> tuple[ExperimentTemplate, ...]:
    selected = template_registry or authoring.registry()
    registered: list[ExperimentTemplate] = []
    for experiment_template in (
        RABI_TEMPLATE,
        READOUT_TEMPLATE,
        SQG_RB_TEMPLATE,
        CZ_RB_TEMPLATE,
    ):
        try:
            registered.append(selected.register(experiment_template))
        except ValidationFailed as error:
            if error.diagnostics[0].code != "experiment_template_duplicate":
                raise
            registered.append(selected.get(experiment_template.id))
    return tuple(registered)


def _build_rabi(
    ctx: ExperimentAuthoringContext,
    *,
    qubit: str,
    sweep: AroundSweep | None = None,
) -> ExperimentSpec:
    qubit_id = ctx.require_subject(qubit)
    ctx.require_binding_capability("drive-stack", "play_pulse_program")
    ctx.require_binding_capability("readout-stack", "capture_dataset")
    length = ctx.around_sweep(
        sweep,
        parameter_id=f"rabi_pulse_length_{qubit_id}",
        default_span=Quantity(value=80.0, unit="ns"),
        default_points=5,
    )
    program = _asset(
        id=f"{qubit_id}-rabi-pulse-program",
        kind="pulse_program",
        media_type="text/x-python",
    )
    return ExperimentSpec(
        id=f"sample-rabi-{qubit_id}",
        kind="sample_rabi",
        points=_points_relation("drive_length", length),
        state=[
            _asset_state("drive-stack", "play_pulse_program", "program", program),
            set_state(
                "drive-stack",
                "play_pulse_program.length",
                col("drive_length"),
            ),
            set_state(
                "drive-stack",
                "play_pulse_program.amplitude",
                param(f"rabi_drive_amplitude_{qubit_id}"),
            ),
            set_state(
                "drive-stack",
                "play_pulse_program.frequency",
                param(f"drive_frequency_{qubit_id}"),
            ),
            set_state(
                "readout-stack",
                "capture_dataset.repetitions",
                param("repetitions"),
            ),
        ],
        assets=[program],
        acquire=acquire(
            "iq",
            repetitions=_repetitions(ctx),
            observations=_observations(_iq_dependents(include_probability=True)),
        ),
        metadata={"template_id": RABI_TEMPLATE_ID},
    )


def _build_readout_frequency(
    ctx: ExperimentAuthoringContext,
    *,
    qubit: str,
    sweep: AroundSweep | None = None,
) -> ExperimentSpec:
    qubit_id = ctx.require_subject(qubit)
    ctx.require_binding_capability("readout-stack", "readout_pulse")
    ctx.require_binding_capability("readout-stack", "capture_dataset")
    readout_frequency_variable = ctx.around_sweep(
        sweep,
        parameter_id=f"readout_frequency_{qubit_id}",
        default_span=Quantity(value=100.0, unit="MHz"),
        default_points=5,
    )
    program = _asset(
        id=f"{qubit_id}-find-frr-with-pi-pulse",
        kind="readout_program",
        media_type="text/x-python",
    )
    return ExperimentSpec(
        id=f"sample-readout-frequency-{qubit_id}",
        kind="sample_readout_frequency",
        points=_points_relation("readout_frequency", readout_frequency_variable),
        state=[
            _asset_state("readout-stack", "readout_pulse", "program", program),
            set_state(
                "readout-stack",
                "readout_pulse.frequency",
                col("readout_frequency"),
            ),
            set_state(
                "readout-stack",
                "readout_pulse.power",
                param(f"readout_power_{qubit_id}"),
            ),
            set_state(
                "readout-stack",
                "capture_dataset.repetitions",
                param("repetitions"),
            ),
        ],
        assets=[program],
        acquire=acquire(
            "iq",
            repetitions=_repetitions(ctx),
            observations=_observations(
                [
                    _table_var(id="iq_amplitude_0", label="IQ Amplitude (0)"),
                    _table_var(id="iq_phase_0", label="IQ phase (0)", unit="rad"),
                    _table_var(id="iq_stdev_0", label="IQ stdev (0)"),
                    _table_var(id="iq_amplitude_1", label="IQ Amplitude (1)"),
                    _table_var(id="iq_phase_1", label="IQ phase (1)", unit="rad"),
                    _table_var(id="iq_stdev_1", label="IQ stdev (1)"),
                ]
            ),
        ),
        metadata={"template_id": READOUT_TEMPLATE_ID},
    )


def _build_sqg_rb(
    ctx: ExperimentAuthoringContext,
    *,
    qubit: str,
    lengths: Sequence[int] | None = None,
    seed: int = 0,
) -> ExperimentSpec:
    qubit_id = ctx.require_subject(qubit)
    ctx.require_binding_capability("drive-stack", "play_gate_sequence")
    ctx.require_binding_capability("drive-stack", "play_pulse_program")
    ctx.require_binding_capability("readout-stack", "capture_dataset")
    clifford_count = _count_points(
        ctx,
        (4, 8, 16) if lengths is None else lengths,
        path="lengths",
    )
    sequence = _asset(
        id=f"{qubit_id}-sqg-rb-sequence",
        kind="gate_sequence",
        media_type="application/vnd.scopecat.opaque+json",
    )
    pulse_program = _asset(
        id=f"{qubit_id}-sqg-rb-pulsedict",
        kind="pulse_program",
        media_type="application/vnd.scopecat.opaque+json",
    )
    return ExperimentSpec(
        id=f"sample-sqg-rb-{qubit_id}",
        kind="sample_sqg_rb",
        points=_points_relation("clifford_count", clifford_count),
        state=[
            _asset_state("drive-stack", "play_gate_sequence", "sequence", sequence),
            _asset_state("drive-stack", "play_pulse_program", "program", pulse_program),
            set_state(
                "drive-stack",
                "play_gate_sequence.clifford_count",
                col("clifford_count"),
            ),
            set_state(
                "drive-stack",
                "play_gate_sequence.seed",
                float(seed),
            ),
            set_state(
                "readout-stack",
                "capture_dataset.repetitions",
                param("repetitions"),
            ),
        ],
        assets=[sequence, pulse_program],
        acquire=acquire(
            "iq",
            repetitions=_repetitions(ctx),
            observations=_observations(_probability_dependents()),
        ),
        metadata={"template_id": SQG_RB_TEMPLATE_ID, "seed": seed},
    )


def _build_cz_rb(
    ctx: ExperimentAuthoringContext,
    *,
    control_qubit: str,
    partner_qubit: str,
    coupler: str = "coupler-q0-q1",
    lengths: Sequence[int] | None = None,
    seed: int = 0,
    interleaved_gate: str = "CZ",
) -> ExperimentSpec:
    control_id = ctx.require_subject(control_qubit)
    partner_id = ctx.require_subject(partner_qubit)
    ctx.require_subject(coupler)
    ctx.require_binding_capability("drive-stack", "play_gate_sequence")
    ctx.require_binding_capability("drive-stack", "play_pulse_program")
    ctx.require_binding_capability("coupler-stack", "play_coupler_pulse")
    ctx.require_binding_capability("readout-stack", "capture_dataset")
    clifford_count = _count_points(
        ctx,
        (2, 4, 8) if lengths is None else lengths,
        path="lengths",
    )
    pair_id = f"{control_id}-{partner_id}"
    sequence = _asset(
        id=f"{pair_id}-cz-rb-sequence",
        kind="gate_sequence",
        media_type="application/vnd.scopecat.opaque+json",
    )
    coupler_program = _asset(
        id=f"{pair_id}-cz-rb-coupler-pulse",
        kind="pulse_program",
        media_type="application/vnd.scopecat.opaque+json",
    )
    return ExperimentSpec(
        id=f"sample-cz-rb-{pair_id}",
        kind="sample_cz_rb",
        points=_points_relation("clifford_count", clifford_count),
        state=[
            _asset_state("drive-stack", "play_gate_sequence", "sequence", sequence),
            set_state(
                "drive-stack",
                "play_gate_sequence.clifford_count",
                col("clifford_count"),
            ),
            _asset_state(
                "coupler-stack",
                "play_coupler_pulse",
                "program",
                coupler_program,
            ),
            set_state(
                "drive-stack",
                "play_gate_sequence.seed",
                float(seed),
            ),
            set_state(
                "readout-stack",
                "capture_dataset.repetitions",
                param("repetitions"),
            ),
        ],
        assets=[sequence, coupler_program],
        acquire=acquire(
            "iq",
            repetitions=_repetitions(ctx),
            observations=_observations(_probability_dependents()),
        ),
        metadata={
            "template_id": CZ_RB_TEMPLATE_ID,
            "seed": seed,
            "interleaved_gate": interleaved_gate,
        },
    )


def _points_relation(variable_id: str, variable: ExperimentVariable) -> RelationExpr:
    if variable.kind == "linspace":
        if variable.start is None or variable.stop is None or variable.count is None:
            msg = f"{variable_id} linspace variable is incomplete"
            raise ValueError(msg)
        return grid(
            **{
                variable_id: linspace(
                    variable.start.value,
                    variable.stop.value,
                    variable.count,
                    unit=variable.start.unit,
                )
            }
        )
    if variable.kind == "points":
        if variable.points is None:
            msg = f"{variable_id} points variable is incomplete"
            raise ValueError(msg)
        return grid(**{variable_id: values(variable.points)})
    msg = f"{variable_id} must be a finite sweep variable"
    raise ValueError(msg)


def _asset_state(
    resource_id: str,
    capability_id: str,
    field_path: str,
    asset: ExperimentAsset,
):
    return set_state(
        resource_id,
        f"{capability_id}.{field_path}",
        {"kind": "asset", "asset_id": asset.id},
    )


def _observations(variables: Sequence[TableVariable]):
    return [observe(variable_id, unit=unit) for variable_id, _label, unit in variables]


def _repetitions(ctx: ExperimentAuthoringContext) -> int:
    repetitions = ctx.require_parameter("repetitions")
    if repetitions.unit != "count":
        ctx.raise_diagnostic(
            "sample_template_repetitions_unit_invalid",
            "repetitions must use count units",
            "repetitions",
        )
    if repetitions.value <= 0 or int(repetitions.value) != repetitions.value:
        ctx.raise_diagnostic(
            "sample_template_repetitions_invalid",
            "repetitions must be a positive integer",
            "repetitions",
        )
    return int(repetitions.value)


def _count_points(
    ctx: ExperimentAuthoringContext,
    values: Sequence[int],
    *,
    path: str,
) -> ExperimentVariable:
    if not values:
        ctx.raise_diagnostic(
            "sample_template_empty_count_axis",
            "count axis must contain at least one value",
            path,
        )
    if any(value <= 0 for value in values):
        ctx.raise_diagnostic(
            "sample_template_invalid_count_axis",
            "count axis values must be positive",
            path,
        )
    return points([float(value) for value in values], unit="count")


def _iq_dependents(*, include_probability: bool) -> list[TableVariable]:
    table_variables = [
        _table_var(id="iq_amplitude", label="IQ Amplitude"),
        _table_var(id="iq_phase", label="IQ phase", unit="rad"),
        _table_var(id="raw_i", label="I", unit="ratio"),
        _table_var(id="raw_q", label="Q", unit="ratio"),
    ]
    if include_probability:
        return [
            _table_var(id="probability_1", label="|1> state prob."),
            *table_variables,
        ]
    return table_variables


def _probability_dependents() -> list[TableVariable]:
    return [
        _table_var(id="probability_0", label="|0> state prob."),
        _table_var(id="probability_1", label="|1> state prob."),
        _table_var(id="raw_i", label="I", unit="ratio"),
        _table_var(id="raw_q", label="Q", unit="ratio"),
    ]


RABI_TEMPLATE = authoring.template(
    id=RABI_TEMPLATE_ID,
    label="Sample Rabi",
    description="Build a sample-backed single-qubit Rabi length scan.",
    inputs=(
        ProviderOptionDescription(id="qubit", dtype="str", required=True),
        ProviderOptionDescription(id="sweep", dtype="AroundSweep | None"),
    ),
    build=_build_rabi,
    metadata={"category": "sample_rabi"},
)

READOUT_TEMPLATE = authoring.template(
    id=READOUT_TEMPLATE_ID,
    label="Sample readout frequency",
    description="Build a sample-backed readout frequency scan.",
    inputs=(
        ProviderOptionDescription(id="qubit", dtype="str", required=True),
        ProviderOptionDescription(id="sweep", dtype="AroundSweep | None"),
    ),
    build=_build_readout_frequency,
    metadata={"category": "sample_readout"},
)

SQG_RB_TEMPLATE = authoring.template(
    id=SQG_RB_TEMPLATE_ID,
    label="Sample SQG RB",
    description="Build a sample-backed single-qubit randomized benchmarking scan.",
    inputs=(
        ProviderOptionDescription(id="qubit", dtype="str", required=True),
        ProviderOptionDescription(id="lengths", dtype="Sequence[int] | None"),
        ProviderOptionDescription(id="seed", dtype="int", default=0),
    ),
    build=_build_sqg_rb,
    metadata={"category": "sample_gate_based"},
)

CZ_RB_TEMPLATE = authoring.template(
    id=CZ_RB_TEMPLATE_ID,
    label="Sample CZ RB",
    description="Build a sample-backed two-qubit CZ randomized benchmarking scan.",
    inputs=(
        ProviderOptionDescription(id="control_qubit", dtype="str", required=True),
        ProviderOptionDescription(id="partner_qubit", dtype="str", required=True),
        ProviderOptionDescription(id="coupler", dtype="str", default="coupler-q0-q1"),
        ProviderOptionDescription(id="lengths", dtype="Sequence[int] | None"),
        ProviderOptionDescription(id="seed", dtype="int", default=0),
        ProviderOptionDescription(id="interleaved_gate", dtype="str", default="CZ"),
    ),
    build=_build_cz_rb,
    metadata={"category": "sample_gate_based"},
)

__all__ = [
    "CZ_RB_TEMPLATE",
    "CZ_RB_TEMPLATE_ID",
    "RABI_TEMPLATE",
    "RABI_TEMPLATE_ID",
    "READOUT_TEMPLATE",
    "READOUT_TEMPLATE_ID",
    "SQG_RB_TEMPLATE",
    "SQG_RB_TEMPLATE_ID",
    "cz_rb",
    "rabi",
    "readout_frequency",
    "register_templates",
    "sqg_rb",
]
