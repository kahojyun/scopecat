"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import (
    Concatenate,
    NoReturn,
    Protocol,
    cast,
    get_type_hints,
    overload,
)

from pydantic import BaseModel, JsonValue

from scopecat.analysis.service import (
    AnalysisDataOutput,
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
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.results import Dataset, ExperimentResultView
from scopecat.records.analysis import (
    AnalysisComputeExecution,
    AnalysisDerivedData,
    AnalysisField,
    AnalysisFigure,
    AnalysisFigureAxis,
    AnalysisFigureSeries,
    AnalysisTable,
    AnalysisTableCell,
    AnalysisTableColumn,
    AnalysisTableRow,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.sdk.compute import compute_implementation_contract_internal


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

    def measurement_batches(self, *, batch_size: int = 100) -> Iterator[Dataset]: ...

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
    """Declarative analysis content before it is saved to its source run."""

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

    def save(self) -> AnalysisOutcome:
        saved = self.run.save_analysis(
            title=self.title,
            analysis_key=self.analysis_key,
            step_id=self.step_id,
            inputs=self.inputs,
            outputs=self.outputs,
            parameter_proposals=self.parameter_proposals,
        )
        return AnalysisOutcome(
            record=saved.record,
            title=self.title,
            analysis_key=saved.analysis_key,
            step_id=self.step_id,
            inputs=self.inputs,
            outputs=self.outputs,
            parameter_proposals=self.parameter_proposals,
        )


@dataclass(frozen=True)
class AnalysisOutcome:
    """One analysis that has been durably published to its source run."""

    record: RunContentEntry
    title: str
    analysis_key: str
    step_id: str | None = None
    inputs: tuple[AnalysisInput, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()

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


@dataclass(frozen=True)
class AnalysisContext:
    run: _AnalysisRun
    default_key: str | None = None
    step_id: str | None = None
    _compute_inputs: list[AnalysisInput] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    _compute_outputs: list[AnalysisDataOutput] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    _compute_ids: dict[str, int] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.run.config

    def measurements(
        self,
        selector: str = "raw-measurements",
    ) -> Dataset:
        """Load a labeled measurement dataset for this analysis step."""

        return self.run.measurements(selector=selector)

    @overload
    def compute[ResultT](
        self,
        data: Dataset,
        /,
        *,
        fn: Callable[[Dataset], ResultT],
        id: str | None = None,
    ) -> ResultT: ...

    @overload
    def compute[ResultT](
        self,
        data: Dataset,
        /,
        *,
        fn: Callable[[Iterator[Dataset]], ResultT],
        id: str | None = None,
    ) -> ResultT: ...

    @overload
    def compute[SchemaT, ResultT](
        self,
        data: ExperimentResultView[SchemaT],
        /,
        *,
        fn: Callable[[ExperimentResultView[SchemaT]], ResultT],
        id: str | None = None,
    ) -> ResultT: ...

    @overload
    def compute[SchemaT, ResultT](
        self,
        data: ExperimentResultView[SchemaT],
        /,
        *,
        fn: Callable[[Iterator[ExperimentResultView[SchemaT]]], ResultT],
        id: str | None = None,
    ) -> ResultT: ...

    def compute[ResultT](
        self,
        data: object,
        /,
        *,
        fn: Callable[..., ResultT],
        id: str | None = None,
    ) -> ResultT:
        """Run one dataset-available compute and retain its durable dependency."""

        dataset = data.dataset if isinstance(data, ExperimentResultView) else data
        if not isinstance(dataset, Dataset):
            raise TypeError("analysis compute requires a Dataset or bound result")
        contract = compute_implementation_contract_internal(fn)
        compute_id = self._allocate_compute_id(
            id or getattr(fn, "__name__", "dataset-compute")
        )
        implementation = (
            contract.reference if contract is not None else f"local:{compute_id}"
        )
        self._compute_inputs.append(
            AnalysisInput(
                target=dataset.entry.id,
                kind="measurement_dataset",
                role="compute-input",
                title=compute_id,
                metadata={
                    "compute": {
                        "id": compute_id,
                        "implementation": implementation,
                        "placement": "dataset",
                        "access": "full" if contract is None else contract.data_access,
                        **(
                            {}
                            if contract is None
                            else {
                                "deterministic": contract.deterministic,
                                "runtime": contract.runtime,
                                "capabilities": list(contract.capabilities),
                            }
                        ),
                    }
                },
            )
        )
        selected_data: object = cast("object", data)
        if contract is not None and contract.data_access == "batches":
            batches = self.run.measurement_batches(batch_size=contract.batch_size)
            selected_data = (
                (batch.bind(cast("object", data.output)) for batch in batches)
                if isinstance(data, ExperimentResultView)
                else batches
            )
        result = fn(selected_data)
        encoded = _analysis_json(result)
        output_hash = f"sha256:{stable_content_hash(encoded)}"
        self._compute_outputs.append(
            AnalysisDataOutput(
                kind="data",
                title=compute_id,
                content=AnalysisDerivedData(
                    codec=(
                        "scopecat.python-json.v1"
                        if contract is None
                        else contract.output_codec
                    ),
                    value=encoded,
                    execution=AnalysisComputeExecution(
                        id=compute_id,
                        implementation=implementation,
                        access=("full" if contract is None else contract.data_access),
                        input_target=dataset.entry.id,
                        input_content_hash=dataset.entry.content_hash,
                        output_content_hash=output_hash,
                        deterministic=(
                            False if contract is None else contract.deterministic
                        ),
                    ),
                ),
                metadata=(
                    {}
                    if contract is None
                    else {
                        "runtime": contract.runtime,
                        "capabilities": list(contract.capabilities),
                        "resources": dict(contract.resources),
                    }
                ),
            )
        )
        return result

    def _allocate_compute_id(self, requested: str) -> str:
        count = self._compute_ids.get(requested, 0) + 1
        self._compute_ids[requested] = count
        return requested if count == 1 else f"{requested}.{count}"

    def result(self, title: str = "analysis", *, key: str | None = None) -> Analysis:
        return replace(
            self.run.analysis(
                title,
                key=key or self.default_key,
                step_id=self.step_id,
            ),
            inputs=tuple(self._compute_inputs),
            outputs=tuple(self._compute_outputs),
        )


def _analysis_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Quantity):
        return {"value": _analysis_json(value.value), "unit": value.unit}
    if isinstance(value, BaseModel):
        return cast("JsonValue", value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return {
            member.name: _analysis_json(cast("object", getattr(value, member.name)))
            for member in fields(value)
        }
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if any(not isinstance(key, str) for key in mapping):
            raise TypeError("analysis derived data mappings require string keys")
        return {cast("str", key): _analysis_json(item) for key, item in mapping.items()}
    if isinstance(value, Sequence):
        return [_analysis_json(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _analysis_json(tolist())
    item = getattr(value, "item", None)
    if callable(item):
        return _analysis_json(item())
    raise TypeError(
        f"analysis compute output {type(value).__qualname__} is not JSON encodable"
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
    "AnalysisField",
    "AnalysisFigure",
    "AnalysisFigureAxis",
    "AnalysisFigureSeries",
    "AnalysisInput",
    "AnalysisInvocation",
    "AnalysisOutcome",
    "AnalysisOutput",
    "AnalysisStep",
    "AnalysisTable",
    "AnalysisTableCell",
    "AnalysisTableColumn",
    "AnalysisTableRow",
    "analysis_step",
]
