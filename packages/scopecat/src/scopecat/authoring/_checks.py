"""Config-free structured checks for public authoring handles."""

from __future__ import annotations

from scopecat.authoring._context import problem
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._resolution import compile_prepared_invocation
from scopecat.authoring._validation import validate_template_definition
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
    TemplateBuilder,
)
from scopecat.checks import (
    CheckPhase,
    CheckPhaseReport,
    CheckStatus,
    ExperimentCheckReport,
)
from scopecat.errors import CheckFailed
from scopecat.problems import Problem, ProblemPhase


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
                    problem(
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
        inputs=dict(compiled.inputs),
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


__all__ = ["check_invocation", "check_template", "check_template_builder"]
