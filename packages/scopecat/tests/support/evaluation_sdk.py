from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.evaluation import (
    ArtifactInputDiagnostics,
    EvaluationContext,
    EvaluationJobArtifact,
    EvaluationStepResult,
)
from scopecat.models.parameter import ParameterChangeSet, ParameterPatch
from scopecat.results import MeasurementDatasetInputDiagnostics


class FakeEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    measurement_count: int


@dataclass(frozen=True)
class FakeEvaluationStep:
    step_id: str = "fake-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        source = context.inputs.resolve_artifact(
            selector="raw-measurements",
            expected_kind="measurement_dataset",
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="fake_evaluation_input_not_found",
                invalid_kind_code="fake_evaluation_input_invalid_kind",
                path_escape_code="fake_evaluation_input_path_escape",
                not_found_message="fake evaluation input artifact not found",
                invalid_kind_message=(
                    "fake evaluation input must be measurement_dataset"
                ),
                path_escape_message=(
                    "fake evaluation input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            source,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="fake_evaluation_input_missing",
                empty_code="fake_evaluation_input_empty",
                invalid_code="fake_evaluation_input_invalid",
                missing_schema_code="fake_evaluation_input_missing_schema",
                invalid_schema_code="fake_evaluation_input_invalid_schema",
                noun="fake evaluation input",
            ),
        )
        measurements = dataset.records
        context.inputs.record_ref("config-profile.snapshot.json")
        context.inputs.record_ref("plan.snapshot.json")
        result = FakeEvaluationResult(
            run_id=context.run_id,
            measurement_count=len(measurements),
        )
        parameter = (
            context.config.parameter_build.get("drive_frequency")
            if context.config.parameter_build is not None
            else None
        )
        assert parameter is not None
        old_value = parameter.quantity
        proposed_value = measurements[0].coordinates["drive_frequency"]
        proposal = ParameterChangeSet(
            id=self.step_id,
            source_run_id=context.run_id,
            reason="Fake evaluation proposal.",
            patches=[
                ParameterPatch(
                    kind="set_scalar",
                    parameter_id="drive_frequency",
                    expected_value=old_value,
                    value=proposed_value,
                )
            ],
            confidence=0.5,
        )
        context.artifacts.write_model(
            id="fake-evaluation-result",
            kind="fake_evaluation_result",
            filename="fake-evaluation.json",
            model=result,
        )
        context.artifacts.write_text(
            id="fake-evaluation-summary",
            kind="summary",
            filename="fake-evaluation.md",
            content="# Fake evaluation\n",
            media_type="text/markdown",
        )
        context.proposals.write_model(
            id="fake-evaluation-proposal",
            kind="parameter_change_set",
            filename="fake-evaluation-proposal.json",
            model=proposal,
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=self.step_id,
            job_ref="evaluation/fake-evaluation.job.json",
            job_artifact=EvaluationJobArtifact(id="fake-evaluation-job"),
        )


@dataclass(frozen=True)
class InvalidArtifactFilenameEvaluationStep:
    step_id: str = "invalid-artifact-filename-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="invalid-artifact-filename-result",
            kind="summary",
            filename="../bad.md",
            content="bad",
        )
        return EvaluationStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="evaluation/invalid-artifact-filename-evaluation.job.json",
        )


@dataclass(frozen=True)
class DuplicateArtifactIdEvaluationStep:
    step_id: str = "duplicate-artifact-id-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="duplicate-artifact",
            kind="summary",
            filename="duplicate-artifact-a.md",
            content="a",
        )
        context.artifacts.write_text(
            id="duplicate-artifact",
            kind="summary",
            filename="duplicate-artifact-b.md",
            content="b",
        )
        return EvaluationStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="evaluation/duplicate-artifact-id-evaluation.job.json",
        )


@dataclass(frozen=True)
class DuplicateArtifactFilenameEvaluationStep:
    step_id: str = "duplicate-artifact-filename-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="duplicate-artifact-a",
            kind="summary",
            filename="duplicate-artifact.md",
            content="a",
        )
        context.artifacts.write_text(
            id="duplicate-artifact-b",
            kind="summary",
            filename="duplicate-artifact.md",
            content="b",
        )
        return EvaluationStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="evaluation/duplicate-artifact-filename-evaluation.job.json",
        )


@dataclass(frozen=True)
class InvalidProposalFilenameEvaluationStep:
    step_id: str = "invalid-proposal-filename-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        proposal = fake_proposal(context)
        context.proposals.write_model(
            id="invalid-proposal-filename",
            kind="parameter_change_set",
            filename="../bad-proposal.json",
            model=proposal,
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=self.step_id,
            job_ref="evaluation/invalid-proposal-filename-evaluation.job.json",
        )


@dataclass(frozen=True)
class DuplicateProposalIdEvaluationStep:
    step_id: str = "duplicate-proposal-id-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        proposal = fake_proposal(context)
        context.proposals.write_model(
            id="duplicate-proposal",
            kind="parameter_change_set",
            filename="duplicate-proposal-a.json",
            model=proposal,
        )
        context.proposals.write_model(
            id="duplicate-proposal",
            kind="parameter_change_set",
            filename="duplicate-proposal-b.json",
            model=proposal,
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=self.step_id,
            job_ref="evaluation/duplicate-proposal-id-evaluation.job.json",
        )


@dataclass(frozen=True)
class DuplicateProposalFilenameEvaluationStep:
    step_id: str = "duplicate-proposal-filename-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        result = FakeEvaluationResult(run_id=context.run_id, measurement_count=0)
        proposal = fake_proposal(context)
        context.proposals.write_model(
            id="duplicate-proposal-a",
            kind="parameter_change_set",
            filename="duplicate-proposal.json",
            model=proposal,
        )
        context.proposals.write_model(
            id="duplicate-proposal-b",
            kind="parameter_change_set",
            filename="duplicate-proposal.json",
            model=proposal,
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=self.step_id,
            job_ref="evaluation/duplicate-proposal-filename-evaluation.job.json",
        )


@dataclass(frozen=True)
class ProposalThenFailEvaluationStep:
    step_id: str = "proposal-then-fail-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        proposal = fake_proposal(context)
        context.proposals.write_model(
            id="partial-failed-proposal",
            kind="parameter_change_set",
            filename="partial-failed-proposal.json",
            model=proposal,
        )
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="fake_after_proposal_failed",
                    message="failed after writing proposal",
                    path="step",
                )
            ]
        )


@dataclass(frozen=True)
class UnexpectedEvaluationFailureStep:
    step_id: str = "unexpected-evaluation"

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[FakeEvaluationResult, ParameterChangeSet]:
        context.artifacts.write_text(
            id="unexpected-evaluation-partial",
            kind="summary",
            filename="unexpected-evaluation-partial.md",
            content="partial",
        )
        raise RuntimeError("boom")


def fake_proposal(context: EvaluationContext) -> ParameterChangeSet:
    parameter = (
        context.config.parameter_build.get("drive_frequency")
        if context.config.parameter_build is not None
        else None
    )
    assert parameter is not None
    old_value = parameter.quantity
    return ParameterChangeSet(
        id="fake-proposal",
        source_run_id=context.run_id,
        reason="Fake proposal.",
        patches=[
            ParameterPatch(
                kind="set_scalar",
                parameter_id="drive_frequency",
                expected_value=old_value,
                value=old_value,
            )
        ],
        confidence=0.5,
    )
