"""Structured, side-effect-free experiment compilation reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from scopecat.authoring._problems import authoring_problem
from scopecat.authoring._validation import validate_template_definition
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
    TemplateBuilder,
)
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ExternalLocation,
    ModelLocation,
    Problem,
    ProblemPhase,
    RuntimeLocation,
    StorageLocation,
    has_blocking_problems,
)
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.records.run import RunConfigSource


class CheckPhase(StrEnum):
    """Stable public names for the experiment checking pipeline."""

    DEFINITION = "definition"
    AUTHORING = "authoring"
    CONFIGURATION = "configuration"
    PLANNING = "planning"


class CheckStatus(StrEnum):
    """Outcome of one check phase or of a complete report."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


def _empty_inputs() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class CheckPhaseReport:
    """The structured problems and outcome produced by one compiler phase."""

    phase: CheckPhase
    status: CheckStatus
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        try:
            phase = CheckPhase(self.phase)
        except ValueError as error:
            msg = "check phase report requires a CheckPhase"
            raise TypeError(msg) from error
        try:
            status = CheckStatus(self.status)
        except ValueError as error:
            msg = "check phase report requires a CheckStatus"
            raise TypeError(msg) from error
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "status", status)
        problems = tuple(self.problems)
        object.__setattr__(self, "problems", problems)
        mismatched = tuple(
            problem for problem in problems if problem.phase.value != self.phase.value
        )
        if mismatched:
            msg = "check phase problems must report the same phase"
            raise ValueError(msg)
        blocking = has_blocking_problems(problems)
        if self.status is CheckStatus.PASSED and blocking:
            msg = "a passed check phase cannot contain blocking problems"
            raise ValueError(msg)
        if self.status is CheckStatus.FAILED and not blocking:
            msg = "a failed check phase requires a blocking problem"
            raise ValueError(msg)
        if self.status is CheckStatus.SKIPPED and problems:
            msg = "a skipped check phase cannot contain problems"
            raise ValueError(msg)

    @property
    def ok(self) -> bool:
        """Whether this phase completed without a blocking problem."""

        return self.status is CheckStatus.PASSED


@dataclass(frozen=True, slots=True)
class ExperimentCheckReport:
    """A structured explanation of how far an experiment can compile.

    ``ok`` means no attempted phase failed. ``complete`` additionally means
    that every phase represented by the report ran. A definition-only template
    check is therefore both successful and complete, while a prepared check
    whose planning phase was skipped is not complete.
    """

    phases: tuple[CheckPhaseReport, ...]
    summary: ExperimentPreview | None = None
    template_id: str | None = None
    inputs: Mapping[str, object] = field(default_factory=_empty_inputs)
    config_source: RunConfigSource | None = None

    def __post_init__(self) -> None:
        phases = tuple(self.phases)
        if not phases:
            msg = "experiment check report requires at least one phase"
            raise ValueError(msg)
        phase_ids = tuple(phase.phase for phase in phases)
        valid_shapes = {
            (CheckPhase.DEFINITION,),
            (CheckPhase.AUTHORING,),
            (
                CheckPhase.AUTHORING,
                CheckPhase.CONFIGURATION,
                CheckPhase.PLANNING,
            ),
        }
        if phase_ids not in valid_shapes:
            msg = "experiment check phases are duplicated, incomplete, or out of order"
            raise ValueError(msg)
        terminal_seen = False
        for phase in phases:
            if terminal_seen and phase.status is not CheckStatus.SKIPPED:
                msg = "phases after a failed or skipped phase must be skipped"
                raise ValueError(msg)
            terminal_seen = terminal_seen or phase.status is not CheckStatus.PASSED
        planning = next(
            (phase for phase in phases if phase.phase is CheckPhase.PLANNING),
            None,
        )
        if self.summary is not None and (
            planning is None or planning.status is not CheckStatus.PASSED
        ):
            msg = "experiment check summary requires a passed planning phase"
            raise ValueError(msg)
        if (
            planning is not None
            and planning.status is CheckStatus.PASSED
            and self.summary is None
        ):
            msg = "a passed planning phase requires an experiment summary"
            raise ValueError(msg)
        raw_inputs = cast("Mapping[object, object]", self.inputs)
        if any(not isinstance(key, str) or not key for key in raw_inputs):
            msg = "experiment check input ids must be non-empty strings"
            raise ValueError(msg)
        selected_inputs = cast("dict[str, object]", dict(raw_inputs))
        object.__setattr__(self, "phases", phases)
        object.__setattr__(self, "inputs", MappingProxyType(selected_inputs))

    @property
    def status(self) -> CheckStatus:
        if any(phase.status is CheckStatus.FAILED for phase in self.phases):
            return CheckStatus.FAILED
        if any(phase.status is CheckStatus.SKIPPED for phase in self.phases):
            return CheckStatus.SKIPPED
        return CheckStatus.PASSED

    @property
    def ok(self) -> bool:
        return self.status is not CheckStatus.FAILED

    @property
    def complete(self) -> bool:
        return all(phase.status is CheckStatus.PASSED for phase in self.phases)

    @property
    def problems(self) -> tuple[Problem, ...]:
        """All phase problems in compiler order."""

        return tuple(problem for phase in self.phases for problem in phase.problems)

    def for_phase(self, phase: CheckPhase) -> CheckPhaseReport:
        """Return one represented phase, raising if it is not in this report."""

        for selected in self.phases:
            if selected.phase is phase:
                return selected
        msg = f"check report does not contain phase {phase.value!r}"
        raise KeyError(msg)

    def explain(self) -> str:
        """Render a deterministic notebook- and log-friendly explanation."""

        lines = [f"experiment check: {self.status.value}"]
        for phase in self.phases:
            lines.append(f"- {phase.phase.value}: {phase.status.value}")
            for problem in phase.problems:
                location = (
                    ""
                    if problem.location is None
                    else f" [{_format_location(problem.location)}]"
                )
                lines.append(
                    f"  - {problem.impact.value} {problem.code}{location}: "
                    f"{problem.message}"
                )
        return "\n".join(lines)


def check_template_builder(builder: TemplateBuilder) -> ExperimentCheckReport:
    """Check a builder without allowing definition failures to escape."""

    try:
        template = builder.build()
    except CheckFailed as error:
        return _definition_failure(error.problems)
    return _checked_template(template, validate=False)


def check_template(template: ExperimentTemplate) -> ExperimentCheckReport:
    """Check only the reusable, config-free template definition."""

    return _checked_template(template, validate=True)


def _checked_template(
    template: ExperimentTemplate,
    *,
    validate: bool,
) -> ExperimentCheckReport:
    if validate:
        module = template.module
        if module is None:
            return _definition_failure(
                (
                    authoring_problem(
                        "experiment_template_missing_module",
                        "experiment template requires a module",
                        "template",
                        path=("module",),
                        phase=ProblemPhase.DEFINITION,
                    ),
                )
            )
        try:
            validate_template_definition(
                module=module,
                inputs=template.inputs,
                default_scans=template.default_scans,
                record_selections=template.record_selections,
            )
        except CheckFailed as error:
            return _definition_failure(error.problems)
    return ExperimentCheckReport(
        phases=(
            CheckPhaseReport(
                phase=CheckPhase.DEFINITION,
                status=CheckStatus.PASSED,
            ),
        ),
        template_id=template.id,
    )


def check_invocation(invocation: ExperimentInvocation) -> ExperimentCheckReport:
    """Compile a bound invocation through the complete config-free pass."""

    try:
        compiled = compile_prepared_invocation(prepare_invocation(invocation))
    except CheckFailed as error:
        return ExperimentCheckReport(
            phases=(
                CheckPhaseReport(
                    phase=CheckPhase.AUTHORING,
                    status=CheckStatus.FAILED,
                    problems=error.problems,
                ),
            ),
            template_id=invocation.template.id,
        )
    return ExperimentCheckReport(
        phases=(
            CheckPhaseReport(
                phase=CheckPhase.AUTHORING,
                status=CheckStatus.PASSED,
            ),
        ),
        template_id=compiled.request.template_id,
        inputs=dict(compiled.assembly.source.inputs),
    )


def _definition_failure(
    problems: list[Problem] | tuple[Problem, ...],
) -> ExperimentCheckReport:
    return ExperimentCheckReport(
        phases=(
            CheckPhaseReport(
                phase=CheckPhase.DEFINITION,
                status=CheckStatus.FAILED,
                problems=tuple(problems),
            ),
        )
    )


def _format_location(
    location: ModelLocation | StorageLocation | ExternalLocation | RuntimeLocation,
) -> str:
    if isinstance(location, ModelLocation):
        selected = location.root
        for item in location.path:
            selected += f"[{item}]" if isinstance(item, int) else f".{item}"
        return selected
    if isinstance(location, StorageLocation):
        identity = location.ref or location.run_id or "storage"
        return ".".join((identity, *(str(item) for item in location.path)))
    if isinstance(location, ExternalLocation):
        cell = ""
        if location.row is not None or location.column is not None:
            cell = f":{location.row!s}:{location.column!s}"
        return f"{location.uri}{cell}"
    parts = [
        value
        for value in (
            location.run_id,
            location.operation_id,
            location.instrument_id,
        )
        if value is not None
    ]
    if location.point_index is not None:
        parts.append(f"point={location.point_index}")
    return "/".join(parts)


__all__ = [
    "CheckPhase",
    "CheckPhaseReport",
    "CheckStatus",
    "ExperimentCheckReport",
    "check_invocation",
    "check_template",
    "check_template_builder",
]
