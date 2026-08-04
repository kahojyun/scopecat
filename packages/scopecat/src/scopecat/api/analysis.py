"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import (
    Concatenate,
    NoReturn,
    Protocol,
    cast,
    get_type_hints,
    overload,
)

from scopecat.analysis.service import (
    AnalysisFigureOutput,
    AnalysisInput,
    AnalysisOutput,
    AnalysisParameterProposalOutput,
    AnalysisTableOutput,
    SavedAnalysis,
)
from scopecat.api.data import Data
from scopecat.config.candidates import (
    CandidateConfig,
    CandidateSelection,
)
from scopecat.config.changes import (
    parameter_change_proposal_from_updates,
)
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.measurements.results import Dataset
from scopecat.records.analysis import (
    AnalysisFigure,
    AnalysisFigureAxis,
    AnalysisFigureSeries,
    AnalysisTable,
    AnalysisTableCell,
    AnalysisTableColumn,
    AnalysisTableRow,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal


class _AnalysisRun(Protocol):
    """Run capabilities consumed by analysis without importing its facade."""

    @property
    def id(self) -> str: ...

    @property
    def config(self) -> ConfigProfileSnapshot: ...

    def data(self) -> Data: ...

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> Dataset: ...

    def analysis(
        self,
        title: str,
        *,
        key: str | None = None,
        step_id: str | None = None,
    ) -> Analysis: ...

    def save_analysis(
        self,
        *,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis: ...


@dataclass(frozen=True)
class Analysis:
    """In-notebook analysis record for exploratory experiment work."""

    run: _AnalysisRun
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: tuple[AnalysisInput, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()

    def table(
        self,
        content: AnalysisTable,
        *,
        title: str = "table",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        return replace(
            self,
            outputs=(
                *self.outputs,
                AnalysisTableOutput(
                    kind="table",
                    title=title,
                    content=content,
                    metadata=metadata or {},
                ),
            ),
        )

    def figure(
        self,
        content: AnalysisFigure,
        *,
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        return replace(
            self,
            outputs=(
                *self.outputs,
                AnalysisFigureOutput(
                    kind="figure",
                    title=title,
                    content=content,
                    metadata=metadata or {},
                ),
            ),
        )

    @property
    def analysis_key(self) -> str:
        return _analysis_key(self.key, self.title)

    def input(
        self,
        selector: str,
        *,
        role: str = "data",
        title: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not role.strip():
            _raise_analysis_problem(
                "analysis_input_role_invalid",
                "analysis input role must be a non-empty string",
                "role",
            )
        dataset = self.run.data().dataset(
            selector,
            expected_kind="measurement_dataset",
        )
        analysis_input = AnalysisInput(
            target=dataset.id,
            kind="measurement_dataset",
            role=role,
            title=title or dataset.id,
            metadata=metadata,
        )
        return replace(self, inputs=(*self.inputs, analysis_input))

    def propose(
        self,
        proposal_id: str,
        *updates: ParameterUpdate,
        reason: str = "",
        confidence: float | None = None,
    ) -> Analysis:
        if not proposal_id.strip():
            _raise_analysis_problem(
                "analysis_parameter_proposal_id_invalid",
                "analysis parameter proposal id must be non-empty",
                "proposal_id",
            )
        if not updates:
            _raise_analysis_problem(
                "analysis_parameter_proposal_empty",
                "analysis parameter proposal requires at least one update",
                "updates",
            )
        if confidence is not None and not 0 <= confidence <= 1:
            _raise_analysis_problem(
                "analysis_parameter_proposal_confidence_invalid",
                "analysis parameter proposal confidence must be between 0 and 1",
                "confidence",
            )
        selected_id = artifact_slug(proposal_id, fallback="analysis")
        if any(proposal.id == selected_id for proposal in self.parameter_proposals):
            _raise_analysis_problem(
                "analysis_parameter_proposal_id_duplicated",
                f"analysis parameter proposal id is duplicated: {selected_id}",
                "proposal_id",
            )
        try:
            proposal = parameter_change_proposal_from_updates(
                source_run_id=self.run.id,
                source_config=self.run.config,
                analysis_title=self.title,
                analysis_record_id=f"analysis-{self.analysis_key}",
                proposal_id=proposal_id,
                updates=updates,
                reason=reason,
                confidence=confidence,
            )
        except (TypeError, ValueError) as error:
            _raise_analysis_problem(
                "analysis_parameter_proposal_invalid",
                str(error),
                "updates",
            )
        output = AnalysisParameterProposalOutput(
            kind="parameter_change_proposal",
            title=selected_id,
            content=proposal,
            metadata={},
        )
        return replace(
            self,
            outputs=(*self.outputs, output),
            parameter_proposals=(*self.parameter_proposals, proposal),
        )

    def candidate_config(
        self,
        selection: CandidateSelection = None,
    ) -> CandidateConfig:
        proposal = _select_candidate_proposal(
            self.parameter_proposals,
            selection=selection,
        )
        return CandidateConfig(
            parameter_proposal=proposal,
        )

    def save(self) -> SavedAnalysis:
        return self.run.save_analysis(
            title=self.title,
            analysis_key=self.analysis_key,
            step_id=self.step_id,
            inputs=self.inputs,
            outputs=self.outputs,
            parameter_proposals=self.parameter_proposals,
        )


@dataclass(frozen=True)
class AnalysisContext:
    run: _AnalysisRun
    default_key: str | None = None
    step_id: str | None = None

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.run.config

    def measurements(
        self,
        selector: str = "raw-measurements",
    ) -> Dataset:
        """Load a labeled measurement dataset for this analysis step."""

        return self.run.measurements(selector=selector)

    def result(self, title: str = "analysis", *, key: str | None = None) -> Analysis:
        return self.run.analysis(
            title,
            key=key or self.default_key,
            step_id=self.step_id,
        )


class AnalysisStep(Protocol):
    @property
    def id(self) -> str: ...

    def run(self, context: AnalysisContext) -> Analysis: ...


type AnalysisFunction = Callable[..., Analysis]


@dataclass(frozen=True, slots=True, repr=False)
class AnalysisInvocation:
    """One configured function-backed analysis step."""

    id: str
    _definition: AnalysisFunction
    arguments: tuple[tuple[str, object], ...]

    def run(self, context: AnalysisContext) -> Analysis:
        """Evaluate the analysis function against one completed run."""

        return self._definition(context, **dict(self.arguments))


@dataclass(frozen=True, slots=True, repr=False)
class AnalysisDefinition[**P]:
    """A reusable analysis function retaining its configuration signature."""

    id: str
    _definition: Callable[Concatenate[AnalysisContext, P], Analysis]
    _signature: inspect.Signature

    @property
    def __wrapped__(self) -> Callable[Concatenate[AnalysisContext, P], Analysis]:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> AnalysisInvocation:
        """Bind analysis configuration without attaching it to a run yet."""

        bound = self._signature.bind(*args, **kwargs)
        return AnalysisInvocation(
            id=self.id,
            _definition=cast("AnalysisFunction", self._definition),
            arguments=tuple(bound.arguments.items()),
        )


@overload
def analysis_step[**P](
    definition: Callable[Concatenate[AnalysisContext, P], Analysis],
    /,
    *,
    id: str | None = None,
) -> AnalysisDefinition[P]: ...


@overload
def analysis_step[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
) -> Callable[
    [Callable[Concatenate[AnalysisContext, P], Analysis]],
    AnalysisDefinition[P],
]: ...


def analysis_step[**P](
    definition: Callable[Concatenate[AnalysisContext, P], Analysis] | None = None,
    /,
    *,
    id: str | None = None,
) -> (
    AnalysisDefinition[P]
    | Callable[
        [Callable[Concatenate[AnalysisContext, P], Analysis]],
        AnalysisDefinition[P],
    ]
):
    """Define a reusable analysis step from a typed Python function."""

    def decorate(
        fn: Callable[Concatenate[AnalysisContext, P], Analysis],
    ) -> AnalysisDefinition[P]:
        return _analysis_definition(fn, id=id)

    return decorate(definition) if definition is not None else decorate


def _analysis_definition[**P](
    fn: Callable[Concatenate[AnalysisContext, P], Analysis],
    *,
    id: str | None,
) -> AnalysisDefinition[P]:
    signature = inspect.signature(fn)
    parameters = tuple(signature.parameters.values())
    if not parameters or parameters[0].kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise TypeError("analysis functions require AnalysisContext first")
    for parameter in parameters[1:]:
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TypeError("analysis configuration requires named parameters")
    hints = cast("Mapping[str, object]", get_type_hints(fn))
    context_annotation = hints.get(
        parameters[0].name,
        cast("object", parameters[0].annotation),
    )
    if context_annotation is not AnalysisContext:
        raise TypeError("analysis functions require an AnalysisContext annotation")
    return_annotation = hints.get(
        "return",
        cast("object", signature.return_annotation),
    )
    if return_annotation is not Analysis:
        raise TypeError("analysis functions must return Analysis")
    selected_id = id or f"{fn.__module__}.{fn.__qualname__}"
    if not selected_id.strip():
        raise ValueError("analysis id must be non-empty")
    return AnalysisDefinition(
        id=selected_id,
        _definition=fn,
        _signature=signature.replace(
            parameters=parameters[1:],
            return_annotation=AnalysisInvocation,
        ),
    )


def _select_candidate_proposal(
    proposals: Sequence[ParameterChangeProposal],
    *,
    selection: CandidateSelection,
) -> ParameterChangeProposal:
    if not proposals:
        _raise_analysis_problem(
            "candidate_config_no_parameter_proposals",
            "candidate config requires at least one parameter proposal",
            "parameter_proposals",
        )
    if selection is None:
        if len(proposals) == 1:
            return proposals[0]
        _raise_analysis_problem(
            "candidate_config_selection_required",
            (
                "candidate config selection is required when analysis has multiple "
                "parameter proposals"
            ),
            "selection",
        )
    by_id = {proposal.id: proposal for proposal in proposals}
    proposal_id = artifact_slug(selection, fallback="analysis")
    try:
        return by_id[proposal_id]
    except KeyError:
        _raise_analysis_problem(
            "candidate_config_selection_not_found",
            f"candidate config selection was not found: {proposal_id}",
            "selection",
        )


def _analysis_key(key: str | None, title: str) -> str:
    selected = key if key is not None else title
    if not selected.strip():
        _raise_analysis_problem(
            "analysis_key_invalid",
            "analysis key must be a non-empty string",
            "key",
        )
    return artifact_slug(selected, fallback="analysis")


def _raise_analysis_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> NoReturn:
    raise CheckFailed(
        [
            problem(
                code,
                message,
                phase=ProblemPhase.ANALYSIS,
                location=model_location("analysis", *path),
            )
        ]
    )


__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisDefinition",
    "AnalysisFigure",
    "AnalysisFigureAxis",
    "AnalysisFigureSeries",
    "AnalysisInput",
    "AnalysisInvocation",
    "AnalysisOutput",
    "AnalysisStep",
    "AnalysisTable",
    "AnalysisTableCell",
    "AnalysisTableColumn",
    "AnalysisTableRow",
    "SavedAnalysis",
    "analysis_step",
]
