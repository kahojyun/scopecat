"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import inspect
import mimetypes
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path, PurePosixPath
from typing import (
    Concatenate,
    Literal,
    NoReturn,
    Protocol,
    cast,
    get_type_hints,
    overload,
)

from pydantic import BaseModel, JsonValue

from scopecat.analysis.datasets import (
    DERIVED_DATASET_CODEC,
    DerivedDataset,
    PandasIndexPolicy,
    derived_dataset,
)
from scopecat.analysis.service import (
    AnalysisArtifactOutput,
    AnalysisDatasetOutput,
    AnalysisFactOutput,
    AnalysisFigureOutput,
    AnalysisInput,
    AnalysisOutput,
    AnalysisParameterProposalOutput,
    AnalysisTableOutput,
    SavedAnalysis,
)
from scopecat.api.data import Data
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.config.changes import (
    parameter_change_proposal_from_updates,
)
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.kernel.content_identity import sha256_content_hash, stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.datasets import MEASUREMENT_DATASET_CODEC
from scopecat.measurements.results import Dataset, ExperimentResultView
from scopecat.records._metadata import validate_json_metadata
from scopecat.records.analysis import (
    ANALYSIS_ARTIFACT_CODEC,
    AnalysisDatasetDerivation,
    AnalysisDatasetViewSource,
    AnalysisExecution,
    AnalysisExecutionInput,
    AnalysisExecutionOutput,
    AnalysisExecutionOutputReference,
    AnalysisFact,
    AnalysisField,
    AnalysisFigure,
    AnalysisFigureAxis,
    AnalysisFigureProjection,
    AnalysisFigureSeries,
    AnalysisFigureView,
    AnalysisTable,
    AnalysisTableCell,
    AnalysisTableColumn,
    AnalysisTableRow,
    AnalysisTableView,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.sdk.compute import (
    PYTHON_JSON_CODEC,
    ComputeImplementationContract,
    compute_capture_names_internal,
    compute_implementation_contract_internal,
    compute_output_encoder_internal,
)


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

    def _measurements_for_analysis(
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
        executions: Sequence[AnalysisExecution],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis: ...

    def published_analysis(self, selector: str) -> PublishedAnalysis: ...


@dataclass(frozen=True)
class Analysis:
    """Declarative analysis content before it is saved to its source run."""

    run: _AnalysisRun
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: tuple[AnalysisInput, ...] = ()
    executions: tuple[AnalysisExecution, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()
    _execution_outputs_by_value_hash: dict[
        str,
        tuple[AnalysisExecutionOutputReference, ...],
    ] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def dataset(
        self,
        id: str,
        content: object,
        *,
        fields: Mapping[str, AnalysisField] | None = None,
        index: PandasIndexPolicy = "auto",
        title: str | None = None,
        metadata: Mapping[str, object] | None = None,
        source: tuple[str, str] | None = None,
    ) -> Analysis:
        """Publish familiar dataframe or array data as one reusable run dataset.

        Pass ``source=(execution_id, output_name)`` only when equal traced
        results make automatic lineage ambiguous.
        """

        if not id.strip():
            _raise_analysis_problem(
                "analysis_dataset_id_invalid",
                "analysis dataset id must be non-empty",
                "id",
            )
        selected_id = artifact_slug(id, fallback="data")
        dataset = derived_dataset(
            content,
            fields=fields,
            index=index,
        )
        produced_by, derived_from = self._dataset_lineage(
            content,
            dataset=dataset,
            fields=fields,
            index=index,
            source=source,
        )
        return self._append_output(
            AnalysisDatasetOutput(
                kind="dataset",
                id=selected_id,
                title=title or selected_id,
                content=dataset,
                metadata=metadata or {},
                produced_by=produced_by,
                derived_from=derived_from,
            )
        )

    def fact(
        self,
        id: str,
        value: object,
        *,
        schema_id: str | None = None,
        title: str | None = None,
        metadata: Mapping[str, object] | None = None,
        source: tuple[str, str] | None = None,
    ) -> Analysis:
        """Publish one small typed conclusion without inventing a dataset.

        Pass ``source=(execution_id, output_name)`` only when equal traced
        results make automatic lineage ambiguous.
        """

        selected_id = _analysis_output_id(id)
        if isinstance(value, Quantity):
            selected_schema = schema_id or "scopecat.quantity.v1"
        elif value is None or isinstance(value, bool | int | float | str):
            selected_schema = schema_id or "scopecat.scalar.v1"
        elif schema_id is None or not schema_id.strip():
            raise TypeError("structured analysis facts require a schema_id")
        else:
            selected_schema = schema_id
        return self._append_output(
            AnalysisFactOutput(
                kind="fact",
                id=selected_id,
                title=title or selected_id,
                content=AnalysisFact(
                    schema_id=selected_schema,
                    codec=PYTHON_JSON_CODEC,
                    value=_analysis_json(value),
                ),
                metadata=metadata or {},
                produced_by=self._source_for(value, source=source),
            )
        )

    def artifact(
        self,
        id: str,
        *,
        path: str | Path | None = None,
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        title: str | None = None,
        metadata: Mapping[str, object] | None = None,
        source: tuple[str, str] | None = None,
    ) -> Analysis:
        """Publish exact file or byte content as part of this analysis.

        Pass ``source=(execution_id, output_name)`` only when equal traced
        byte results make automatic lineage ambiguous.
        """

        selected_id = _analysis_output_id(id)
        selected_sources = (path is not None, text is not None, content is not None)
        if sum(selected_sources) != 1:
            raise TypeError(
                "analysis artifact requires exactly one path, text, or content"
            )
        source_path = None if path is None else Path(path)
        if source_path is not None and not source_path.is_file():
            raise FileNotFoundError(source_path)
        selected_filename = filename or (
            source_path.name
            if source_path is not None
            else f"{selected_id}.{'txt' if text is not None else 'bin'}"
        )
        if not _is_artifact_filename(selected_filename):
            raise ValueError("analysis artifact filename must be a basename")
        selected_content = (
            source_path.read_bytes()
            if source_path is not None
            else (text.encode() if text is not None else content)
        )
        assert selected_content is not None
        selected_media_type = media_type or mimetypes.guess_type(selected_filename)[0]
        if selected_media_type is None:
            selected_media_type = (
                "text/plain" if text is not None else "application/octet-stream"
            )
        return self._append_output(
            AnalysisArtifactOutput(
                kind="artifact",
                id=selected_id,
                title=title or selected_id,
                content=selected_content,
                filename=selected_filename,
                media_type=selected_media_type,
                metadata=metadata or {},
                produced_by=self._source_for(selected_content, source=source),
            )
        )

    @overload
    def table(
        self,
        content: DerivedDataset | AnalysisTable | Sequence[object],
        *,
        id: str = "table",
        columns: Sequence[str] | None = None,
        title: str = "table",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis: ...

    @overload
    def table(
        self,
        *,
        dataset: str,
        id: str = "table",
        columns: Sequence[str] | None = None,
        title: str = "table",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis: ...

    def table(
        self,
        content: DerivedDataset | AnalysisTable | Sequence[object] | None = None,
        *,
        dataset: str | None = None,
        id: str = "table",
        columns: Sequence[str] | None = None,
        title: str = "table",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if (content is None) == (dataset is None):
            raise TypeError(
                "analysis table requires exactly one content or dataset source"
            )
        source = self._dataset(dataset) if dataset is not None else content
        if isinstance(source, DerivedDataset):
            table = source.to_analysis_table(columns=columns)
        elif columns is not None:
            raise TypeError("analysis table columns only apply to derived datasets")
        elif isinstance(source, AnalysisTable):
            table = source
        else:
            assert source is not None
            table = AnalysisTable.from_objects(source)
        source_ref = (
            None
            if dataset is None
            else AnalysisDatasetViewSource(
                output_id=artifact_slug(dataset, fallback="data")
            )
        )
        return self._append_output(
            AnalysisTableOutput(
                kind="table",
                id=_analysis_output_id(id),
                title=title,
                content=AnalysisTableView(
                    source=source_ref,
                    columns=(
                        None
                        if source_ref is None
                        else tuple(column.id for column in table.columns)
                    ),
                    preview=table,
                ),
                metadata=metadata or {},
            )
        )

    @overload
    def figure(
        self,
        content: AnalysisFigure,
        *,
        id: str = "figure",
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis: ...

    @overload
    def figure(
        self,
        content: DerivedDataset | AnalysisTable | Sequence[object],
        *,
        id: str = "figure",
        kind: Literal["line", "scatter"],
        x: str,
        y: str,
        series: str | None = None,
        label: str | None = None,
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis: ...

    @overload
    def figure(
        self,
        *,
        dataset: str,
        id: str = "figure",
        kind: Literal["line", "scatter"],
        x: str,
        y: str,
        series: str | None = None,
        label: str | None = None,
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis: ...

    def figure(
        self,
        content: (
            DerivedDataset | AnalysisFigure | AnalysisTable | Sequence[object] | None
        ) = None,
        *,
        dataset: str | None = None,
        id: str = "figure",
        kind: Literal["line", "scatter"] | None = None,
        x: str | None = None,
        y: str | None = None,
        series: str | None = None,
        label: str | None = None,
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if (content is None) == (dataset is None):
            raise TypeError(
                "analysis figure requires exactly one content or dataset source"
            )
        source = self._dataset(dataset) if dataset is not None else content
        if isinstance(source, AnalysisFigure):
            figure = source
        else:
            if kind is None or x is None or y is None:
                raise TypeError(
                    "analysis figures projected from rows require kind, x, and y"
                )
            if isinstance(source, DerivedDataset):
                selected_columns = tuple(
                    dict.fromkeys((x, y) if series is None else (x, y, series))
                )
                table = source.to_analysis_table(columns=selected_columns)
            elif isinstance(source, AnalysisTable):
                table = source
            else:
                assert source is not None
                table = AnalysisTable.from_objects(source)
            figure = AnalysisFigure.from_table(
                table,
                kind=kind,
                x=x,
                y=y,
                series=series,
                label=label,
            )
        source_ref = (
            None
            if dataset is None
            else AnalysisDatasetViewSource(
                output_id=artifact_slug(dataset, fallback="data")
            )
        )
        return self._append_output(
            AnalysisFigureOutput(
                kind="figure",
                id=_analysis_output_id(id),
                title=title,
                content=AnalysisFigureView(
                    source=source_ref,
                    projection=(
                        None
                        if source_ref is None
                        else AnalysisFigureProjection(
                            kind=cast("Literal['line', 'scatter']", kind),
                            x=cast("str", x),
                            y=cast("str", y),
                            series=series,
                            label=label,
                        )
                    ),
                    preview=figure,
                ),
                metadata=metadata or {},
            )
        )

    def _dataset(self, id: str) -> DerivedDataset:
        selected_id = artifact_slug(id, fallback="data")
        for output in self.outputs:
            if isinstance(output, AnalysisDatasetOutput) and output.id == selected_id:
                return output.content
        raise KeyError(f"analysis has no dataset output: {selected_id}")

    def _append_output(self, output: AnalysisOutput) -> Analysis:
        if any(existing.id == output.id for existing in self.outputs):
            _raise_analysis_problem(
                "analysis_output_id_duplicated",
                f"analysis output id is duplicated: {output.id}",
                "id",
            )
        return replace(self, outputs=(*self.outputs, output))

    def _source_for(
        self,
        value: object,
        *,
        source: tuple[str, str] | None,
    ) -> AnalysisExecutionOutputReference | None:
        if source is not None:
            return AnalysisExecutionOutputReference(
                execution_id=source[0],
                output_name=source[1],
            )
        try:
            content_hash = _analysis_value_hash(value)
        except TypeError:
            return None
        candidates = self._execution_outputs_by_value_hash.get(content_hash, ())
        return candidates[0] if len(candidates) == 1 else None

    def _dataset_lineage(
        self,
        value: object,
        *,
        dataset: DerivedDataset,
        fields: Mapping[str, AnalysisField] | None,
        index: PandasIndexPolicy,
        source: tuple[str, str] | None,
    ) -> tuple[
        AnalysisExecutionOutputReference | None,
        AnalysisDatasetDerivation | None,
    ]:
        exact = self._source_for(dataset, source=source)
        if exact is not None and self._execution_output_matches(
            exact,
            value=dataset,
        ):
            return exact, None
        traced_source = exact or self._source_for(value, source=source)
        if traced_source is None:
            return None, None
        if not self._execution_output_matches(traced_source, value=value):
            raise ValueError(
                "analysis dataset source content does not match its execution output"
            )
        return None, AnalysisDatasetDerivation(
            source=traced_source,
            source_kind=_analysis_dataset_source_kind(value),
            fields=dict(fields or {}),
            index=index,
        )

    def _execution_output_matches(
        self,
        reference: AnalysisExecutionOutputReference,
        *,
        value: object,
    ) -> bool:
        execution_output = next(
            (
                output
                for execution in self.executions
                if execution.id == reference.execution_id
                for output in execution.outputs
                if output.name == reference.output_name
            ),
            None,
        )
        if execution_output is None:
            raise ValueError("analysis source must identify a traced execution output")
        codec, content_hash = _analysis_value_identity(value)
        return (
            execution_output.codec == codec
            and execution_output.content_hash == content_hash
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
            content_hash=dataset.content_hash,
            codec=MEASUREMENT_DATASET_CODEC,
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
            id=proposal.id,
            title=selected_id,
            content=proposal,
            metadata={},
        )
        analysis = self._append_output(output)
        return replace(
            analysis,
            parameter_proposals=(*self.parameter_proposals, proposal),
        )

    def save(self) -> PublishedAnalysis:
        saved = self.run.save_analysis(
            title=self.title,
            analysis_key=self.analysis_key,
            step_id=self.step_id,
            inputs=self.inputs,
            executions=self.executions,
            outputs=self.outputs,
            parameter_proposals=self.parameter_proposals,
        )
        return self.run.published_analysis(saved.record.id)


@dataclass(frozen=True)
class AnalysisContext:
    run: _AnalysisRun
    default_key: str | None = None
    step_id: str | None = None
    _executions: list[AnalysisExecution] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    _execution_ids: dict[str, int] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _accessed_inputs: dict[str, AnalysisInput] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _execution_outputs_by_value_hash: dict[
        str,
        tuple[AnalysisExecutionOutputReference, ...],
    ] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _execution_targets_by_value_hash: dict[str, tuple[str, ...]] = field(
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

        dataset = self.run._measurements_for_analysis(  # pyright: ignore[reportPrivateUsage]
            selector=selector
        )
        self._accessed_inputs.setdefault(
            dataset.entry.id,
            AnalysisInput(
                target=dataset.entry.id,
                kind="measurement_dataset",
                content_hash=dataset.entry.content_hash,
                codec=MEASUREMENT_DATASET_CODEC,
                role="data",
                title=dataset.entry.id,
            ),
        )
        return dataset

    @overload
    def trace[ResultT](
        self,
        id: str | None = None,
        *,
        fn: Callable[..., ResultT],
        inputs: None = None,
        **input_bindings: object,
    ) -> ResultT: ...

    @overload
    def trace[ResultT](
        self,
        id: str | None = None,
        *,
        fn: Callable[..., ResultT],
        inputs: Mapping[str, object],
        **input_bindings: object,
    ) -> ResultT: ...

    def trace(
        self,
        id: str | None = None,
        *,
        fn: Callable[..., object],
        inputs: Mapping[str, object] | None = None,
        **input_bindings: object,
    ) -> object:
        """Run ordinary analysis code while retaining optional execution evidence."""

        duplicate_inputs = set(inputs or {}) & set(input_bindings)
        if duplicate_inputs:
            rendered = ", ".join(sorted(duplicate_inputs))
            raise TypeError(f"analysis trace inputs were bound twice: {rendered}")
        selected_inputs = {**(inputs or {}), **input_bindings}
        if not selected_inputs:
            raise TypeError("analysis trace requires at least one named input")
        dataset_inputs: dict[
            str,
            Dataset | DerivedDataset | ExperimentResultView[object],
        ] = {}
        for name, value in selected_inputs.items():
            if isinstance(value, Dataset | DerivedDataset):
                dataset_inputs[name] = value
            elif isinstance(value, ExperimentResultView):
                dataset_inputs[name] = cast("ExperimentResultView[object]", value)
        if not dataset_inputs:
            raise TypeError("analysis trace requires at least one dataset input")
        contract = compute_implementation_contract_internal(fn)
        execution_id = self._allocate_execution_id(
            id or getattr(fn, "__name__", "analysis-execution")
        )
        implementation = (
            contract.reference if contract is not None else f"python:{execution_id}"
        )
        deterministic = False if contract is None else contract.deterministic
        captures = compute_capture_names_internal(fn)
        if (
            contract is not None
            and contract.input_codecs
            and set(contract.input_codecs) != set(selected_inputs)
        ):
            raise ValueError(
                "registered analysis trace input codecs must exactly match "
                "its named inputs"
            )
        input_provenance = tuple(
            _analysis_execution_input(
                name,
                value,
                codec=(None if contract is None else contract.input_codecs.get(name)),
                execution_target=self._execution_target_for(value),
            )
            for name, value in selected_inputs.items()
        )
        input_names = tuple(selected_inputs)
        for provenance in input_provenance:
            if provenance.kind != "measurement_dataset":
                continue
            self._accessed_inputs.setdefault(
                provenance.target,
                AnalysisInput(
                    target=provenance.target,
                    kind="measurement_dataset",
                    content_hash=provenance.content_hash,
                    codec=provenance.codec,
                    role="data",
                    title=provenance.target,
                ),
            )

        call_inputs = dict(selected_inputs)
        if contract is not None and contract.data_access == "batches":
            if len(dataset_inputs) != 1:
                raise ValueError(
                    "batched analysis trace requires exactly one dataset input"
                )
            dataset_name, data = next(iter(dataset_inputs.items()))
            if isinstance(data, DerivedDataset):
                raise ValueError(
                    "batched analysis trace requires a measurement dataset input"
                )
            dataset = data.dataset if isinstance(data, ExperimentResultView) else data
            batches = dataset.batches(batch_size=contract.batch_size)
            call_inputs[dataset_name] = (
                (batch.bind(data.output) for batch in batches)
                if isinstance(data, ExperimentResultView)
                else batches
            )
        result = fn(**call_inputs)
        encoder = compute_output_encoder_internal(fn)
        traced_values, execution_outputs = _analysis_trace_outputs(
            result,
            execution_id=execution_id,
            contract=contract,
            encoder=encoder,
        )
        execution_metadata = validate_json_metadata(
            {}
            if contract is None
            else {
                "runtime": contract.runtime,
                "capabilities": list(contract.capabilities),
                "resources": dict(contract.resources),
            }
        )
        execution = AnalysisExecution(
            id=execution_id,
            implementation=implementation,
            deterministic=deterministic,
            inputs=input_names,
            input_bindings=input_provenance,
            outputs=execution_outputs,
            captures=captures,
            access=("full" if contract is None else contract.data_access),
            metadata=execution_metadata,
        )
        self._executions.append(execution)
        for (output_name, value), execution_output in zip(
            traced_values,
            execution.outputs,
            strict=True,
        ):
            try:
                value_codec, value_hash = _analysis_value_identity(value)
            except TypeError:
                continue
            if (
                value_codec != execution_output.codec
                or value_hash != execution_output.content_hash
            ):
                continue
            reference = AnalysisExecutionOutputReference(
                execution_id=execution.id,
                output_name=output_name,
            )
            self._record_execution_value(
                content_hash=value_hash,
                reference=reference,
            )
        return result

    def _allocate_execution_id(self, requested: str) -> str:
        base = artifact_slug(requested, fallback="analysis-execution")
        count = self._execution_ids.get(base, 0) + 1
        self._execution_ids[base] = count
        return base if count == 1 else f"{base}-{count}"

    def _execution_target_for(self, value: object) -> str | None:
        try:
            content_hash = _analysis_value_hash(value)
        except TypeError:
            return None
        targets = self._execution_targets_by_value_hash.get(content_hash, ())
        return targets[0] if len(targets) == 1 else None

    def _record_execution_value(
        self,
        *,
        content_hash: str,
        reference: AnalysisExecutionOutputReference,
    ) -> None:
        references = self._execution_outputs_by_value_hash.get(content_hash, ())
        if reference not in references:
            self._execution_outputs_by_value_hash[content_hash] = (
                *references,
                reference,
            )
        target = f"execution:{reference.execution_id}:{reference.output_name}"
        targets = self._execution_targets_by_value_hash.get(content_hash, ())
        if target not in targets:
            self._execution_targets_by_value_hash[content_hash] = (*targets, target)

    def result(self, title: str = "analysis", *, key: str | None = None) -> Analysis:
        return replace(
            self.run.analysis(
                title,
                key=key or self.default_key,
                step_id=self.step_id,
            ),
            inputs=tuple(self._accessed_inputs.values()),
            executions=tuple(self._executions),
            _execution_outputs_by_value_hash=dict(
                self._execution_outputs_by_value_hash
            ),
        )


def _analysis_trace_outputs(
    result: object,
    *,
    execution_id: str,
    contract: ComputeImplementationContract | None,
    encoder: Callable[[object], object] | None,
) -> tuple[
    tuple[tuple[str, object], ...],
    tuple[AnalysisExecutionOutput, ...],
]:
    if contract is not None and contract.outputs:
        traced_values = tuple(
            (name, _analysis_result_at_path(result, path))
            for name, path in contract.outputs.items()
        )
        return traced_values, tuple(
            _analysis_native_execution_output(name=name, value=value)
            for name, value in traced_values
        )
    output = result if encoder is None else encoder(result)
    artifact_output = _analysis_artifact_value(output)
    dataset_output = _analysis_dataset_value(output)
    if artifact_output is not None:
        if contract is not None and contract.output_codec != PYTHON_JSON_CODEC:
            raise ValueError("artifact trace outputs own their bytes codec")
        output_codec = ANALYSIS_ARTIFACT_CODEC
        output_hash = sha256_content_hash(artifact_output)
        output_kind: Literal["derived_dataset", "artifact", "value"] = "artifact"
    elif dataset_output is not None:
        if contract is not None and contract.output_codec != PYTHON_JSON_CODEC:
            raise ValueError("derived dataset trace outputs own their Arrow IPC codec")
        output_codec = DERIVED_DATASET_CODEC
        output_hash = sha256_content_hash(dataset_output.to_arrow_ipc())
        output_kind = "derived_dataset"
    else:
        encoded = _analysis_json(output)
        output_codec = PYTHON_JSON_CODEC if contract is None else contract.output_codec
        output_hash = f"sha256:{stable_content_hash(encoded)}"
        output_kind = "value"
    return ((execution_id, result),), (
        AnalysisExecutionOutput(
            name=execution_id,
            kind=output_kind,
            content_hash=output_hash,
            codec=output_codec,
        ),
    )


def _analysis_execution_input(
    name: str,
    value: object,
    *,
    codec: str | None,
    execution_target: str | None,
) -> AnalysisExecutionInput:
    artifact = _analysis_artifact_value(value)
    if artifact is not None:
        if codec is not None and codec != ANALYSIS_ARTIFACT_CODEC:
            raise ValueError("artifact trace inputs require the artifact bytes codec")
        content_hash = sha256_content_hash(artifact)
        return AnalysisExecutionInput(
            name=name,
            kind="artifact",
            target=execution_target or f"content:{content_hash}",
            content_hash=content_hash,
            codec=ANALYSIS_ARTIFACT_CODEC,
        )
    if isinstance(value, DerivedDataset):
        if codec is not None and codec != DERIVED_DATASET_CODEC:
            raise ValueError("derived dataset trace inputs require the Arrow IPC codec")
        content_hash = sha256_content_hash(value.to_arrow_ipc())
        return AnalysisExecutionInput(
            name=name,
            kind="derived_dataset",
            target=execution_target or f"content:{content_hash}",
            content_hash=content_hash,
            codec=DERIVED_DATASET_CODEC,
        )
    dataset = (
        cast("ExperimentResultView[object]", value).dataset
        if isinstance(value, ExperimentResultView)
        else value
    )
    if isinstance(dataset, Dataset):
        return AnalysisExecutionInput(
            name=name,
            kind="measurement_dataset",
            target=dataset.entry.id,
            content_hash=dataset.entry.content_hash,
            codec=codec or MEASUREMENT_DATASET_CODEC,
        )
    if codec is not None and codec != PYTHON_JSON_CODEC:
        raise ValueError("inline analysis trace inputs require the Python JSON codec")
    encoded = _analysis_json(cast("object", value))
    content_hash = f"sha256:{stable_content_hash(encoded)}"
    return AnalysisExecutionInput(
        name=name,
        kind="value",
        target=execution_target or f"inline:{name}:{content_hash}",
        content_hash=content_hash,
        codec=PYTHON_JSON_CODEC,
        value=None if execution_target is not None else encoded,
    )


def _analysis_value_hash(value: object) -> str:
    return _analysis_value_identity(value)[1]


def _analysis_value_identity(value: object) -> tuple[str, str]:
    artifact = _analysis_artifact_value(value)
    if artifact is not None:
        return ANALYSIS_ARTIFACT_CODEC, sha256_content_hash(artifact)
    dataset = _analysis_dataset_value(value)
    if dataset is not None:
        return DERIVED_DATASET_CODEC, sha256_content_hash(dataset.to_arrow_ipc())
    return PYTHON_JSON_CODEC, f"sha256:{stable_content_hash(_analysis_json(value))}"


def _analysis_native_execution_output(
    *,
    name: str,
    value: object,
) -> AnalysisExecutionOutput:
    codec, content_hash = _analysis_value_identity(value)
    artifact = _analysis_artifact_value(value)
    dataset = _analysis_dataset_value(value)
    return AnalysisExecutionOutput(
        name=name,
        kind=(
            "artifact"
            if artifact is not None
            else ("derived_dataset" if dataset is not None else "value")
        ),
        content_hash=content_hash,
        codec=codec,
    )


def _analysis_result_at_path(
    result: object,
    path: tuple[str | int, ...],
) -> object:
    selected = result
    for item in path:
        if isinstance(item, int):
            if not isinstance(selected, Sequence) or isinstance(
                selected,
                str | bytes | bytearray,
            ):
                raise TypeError(
                    f"analysis result path {path!r} cannot index "
                    f"{type(selected).__qualname__} by position"
                )
            selected = selected[item]
        elif isinstance(selected, Mapping):
            selected = cast("Mapping[object, object]", selected)[item]
        else:
            try:
                selected = cast("object", getattr(selected, item))
            except AttributeError:
                raise TypeError(
                    f"analysis result path {path!r} cannot read field {item!r} "
                    f"from {type(selected).__qualname__}"
                ) from None
    return selected


def _analysis_dataset_value(value: object) -> DerivedDataset | None:
    if isinstance(value, DerivedDataset):
        return value
    owner = type(value).__module__.partition(".")[0]
    if owner in {"pandas", "polars", "pyarrow", "xarray"}:
        return derived_dataset(value)
    return None


def _analysis_artifact_value(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, Path):
        if not value.is_file():
            raise FileNotFoundError(value)
        return value.read_bytes()
    return None


def _analysis_dataset_source_kind(
    value: object,
) -> Literal["arrow", "pandas", "polars", "xarray"]:
    owner = type(value).__module__.partition(".")[0]
    if owner == "pyarrow":
        return "arrow"
    if owner in {"pandas", "polars", "xarray"}:
        return cast("Literal['pandas', 'polars', 'xarray']", owner)
    raise TypeError("analysis dataset derivations require native dataset content")


def _analysis_json(value: object) -> JsonValue:
    if isinstance(value, DerivedDataset):
        return value.to_json_value()
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
        f"analysis trace output {type(value).__qualname__} is not JSON encodable"
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


def _analysis_key(key: str | None, title: str) -> str:
    selected = key if key is not None else title
    if not selected.strip():
        _raise_analysis_problem(
            "analysis_key_invalid",
            "analysis key must be a non-empty string",
            "key",
        )
    return artifact_slug(selected, fallback="analysis")


def _analysis_output_id(value: str) -> str:
    if not value.strip():
        _raise_analysis_problem(
            "analysis_output_id_invalid",
            "analysis output id must be a non-empty string",
            "id",
        )
    return artifact_slug(value, fallback="output")


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


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
    "AnalysisOutput",
    "AnalysisStep",
    "AnalysisTable",
    "AnalysisTableCell",
    "AnalysisTableColumn",
    "AnalysisTableRow",
    "DerivedDataset",
    "analysis_step",
]
