from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol, cast

import pytest

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.api.run import RunHandle
from scopecat.authoring import (
    Experiment,
    ExperimentInvocation,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.results import Dataset
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import config_content_hash
from scopecat.records.measurement import MeasurementRecord, MeasurementScalar
from scopecat.records.run import AnalysisCandidateRunConfigSource
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import DRIVE_FREQUENCY_POINT
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.instrument_host import compose_test_instruments
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1")
_SET_FREQUENCY_VALUE = _SET_FREQUENCY.property("frequency")
_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_VALUE = _SCALAR_SIGNAL.acquisition("sample").result("signal")


class _ArrowColumn(Protocol):
    def to_pylist(self) -> list[object]: ...


class _ArrowTable(Protocol):
    @property
    def num_rows(self) -> int: ...

    def __getitem__(self, name: str) -> _ArrowColumn: ...


class _ArrowSchema(Protocol):
    @property
    def names(self) -> list[str]: ...


class _ArrowRecordBatch(Protocol):
    @property
    def num_rows(self) -> int: ...

    @property
    def schema(self) -> _ArrowSchema: ...

    def __getitem__(self, name: str) -> _ArrowColumn: ...


class _ArrowRecordBatchReader(Protocol):
    @property
    def schema(self) -> _ArrowSchema: ...

    def __iter__(self) -> Iterator[_ArrowRecordBatch]: ...


@dataclass(frozen=True, slots=True)
class _ComputeOnlyResult:
    score: sc.ValueRef[float]


@dataclass(frozen=True, slots=True)
class _ConvertedQuantityResult:
    voltage: sc.ValueRef[sc.Quantity]


@dataclass(frozen=True, slots=True)
class _StructuredComputeResult(sc.ProductBundle):
    doubled: Annotated[sc.DataRef[int], sc.ScalarType(sc.IntType())]
    label: Annotated[sc.DataRef[str], sc.ScalarType(sc.StringType())]


@_StructuredComputeResult.kernel
def _structured_compute(*, value: int) -> tuple[int, str]:
    return value * 2, f"value-{value}"


@authoring.module(id="test.session.simple_frequency_scan")
def SIMPLE_FREQUENCY_SCAN(
    module: authoring.ModuleContext,
    frequency: Annotated[
        authoring.Input[Quantity],
        authoring.ScalarType(authoring.QuantityType(unit="GHz")),
    ],
) -> authoring.ProductRef:
    source = module._resource(
        "source",
        requires=(_SET_FREQUENCY, _SCALAR_SIGNAL),
    )
    module._bind_property(
        source,
        _SET_FREQUENCY_VALUE,
        value=frequency,
    )
    signal = module._product("signal", unit="ratio")
    module._acquire(
        "read-signal",
        resource=source,
        results={_SCALAR_SIGNAL_VALUE: signal},
    )
    return signal


def _quantity_coordinate(record: MeasurementRecord, coordinate_id: str) -> Quantity:
    value = record.coordinates[coordinate_id]
    assert isinstance(value, MeasurementScalar)
    assert value.dtype in {"float64", "int64"}
    assert isinstance(value.value, int | float) and not isinstance(value.value, bool)
    assert value.unit is not None
    return Quantity(float(value.value), value.unit)


def simple_frequency_scan(*, subject: str) -> ExperimentInvocation:
    return simple_frequency_scan_experiment().bind(subject=subject)


def simple_frequency_scan_experiment() -> Experiment[...]:
    def definition(
        experiment: authoring.ExperimentContext,
        subject: Annotated[
            authoring.Input[sc.EntityRef | str],
            authoring.EntityType(),
        ],
    ) -> None:
        del subject
        signal = experiment.use(SIMPLE_FREQUENCY_SCAN(frequency=DRIVE_FREQUENCY_POINT))
        experiment.grid(
            sc.axis(
                DRIVE_FREQUENCY_POINT,
                center=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType()),
                ),
                span=Quantity(value=200.0, unit="MHz"),
                points=3,
            ),
        )
        experiment.alias(signal, record_id="signal")

    return authoring.experiment(
        id="test.session.simple_frequency_scan",
        kind="simple_frequency_scan",
    )(definition)


def test_in_process_lab_runs_experiment_spec(tmp_path: Path) -> None:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    preview = lab.prepare(load_invocation()).preview()

    assert preview.point_count == 3
    assert preview.primary_observables == ("signal",)
    assert [
        (binding.id, binding.kind, binding.owner, binding.origin)
        for binding in preview.bindings
    ] == [
        ("subject", "input", "invocation", "override"),
        ("drive_frequency", "coordinate", "point-plan", "around"),
        ("drive_frequency", "parameter", "configuration", None),
    ]
    [edge] = preview.binding_edges
    assert (edge.source.kind, edge.source.id) == (
        "parameter",
        "drive_frequency",
    )
    assert (edge.relation, edge.target.kind, edge.target.id) == (
        "centers",
        "coordinate",
        "drive_frequency",
    )


def test_in_process_lab_records_compute_value_without_instruments(
    tmp_path: Path,
) -> None:
    @sc.experiment(id="test.session.compute-only", kind="compute-only")
    def compute_only(experiment: sc.ExperimentContext) -> _ComputeOnlyResult:
        selected_score = 2.5

        def calculate_score() -> float:
            return selected_score

        score = cast(
            "sc.ValueRef[float]",
            experiment.compute(fn=calculate_score),
        )
        return _ComputeOnlyResult(score=score)

    config = load_config()
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=ExperimentSystem(
            instrument_catalog=InstrumentContractCatalog(
                config_content_hash=config_content_hash(config)
            )
        ),
    )

    preview = lab.prepare(compute_only).preview()
    assert preview.host_compute_ids == ("calculate_score",)
    assert preview.observation_compute_ids == ()
    [compute] = preview.computes
    assert compute.inputs == ()
    assert compute.outputs == ("calculate_score",)
    assert compute.demanded_by == ("record:score",)
    assert compute.implementation.startswith("python:")
    assert not compute.deterministic
    assert compute.captures == ("selected_score",)

    run = lab.prepare(compute_only).run()
    dataset = run.measurements()
    stored_result = run.result()
    typed_result = run.result(compute_only().output)

    assert run.manifest.status == "completed"
    assert isinstance(dataset, Dataset)
    assert dataset.entry.id == "raw-measurements"
    [record] = dataset.records
    assert record.observables["score"] == MeasurementScalar.create(
        dtype="float64",
        value=2.5,
    )
    variable = next(item for item in dataset.schema.variables if item.id == "score")
    assert variable.source_value_id == "calculate_score"
    assert stored_result.contract.id == "test.session.compute-only"
    assert stored_result.paths == (("score",),)
    assert stored_result[0].value("score") == 2.5
    assert typed_result[0].value(typed_result.output.score) == 2.5
    content = run.data()
    assert content.datasets == ("raw-measurements",)
    assert content.dataset("raw-measurements") == dataset.entry


def test_structured_host_compute_is_one_public_compute(tmp_path: Path) -> None:
    @sc.experiment(id="test.session.structured-compute")
    def structured(experiment: sc.ExperimentContext) -> _StructuredComputeResult:
        return experiment.compute(fn=_structured_compute, value=3)

    config = load_config()
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=ExperimentSystem(
            instrument_catalog=InstrumentContractCatalog(
                config_content_hash=config_content_hash(config)
            )
        ),
    )

    prepared = lab.prepare(structured())
    preview = prepared.preview()
    [compute] = preview.computes
    assert compute.id == "structured_compute"
    assert compute.placement == "host"
    assert compute.inputs == ("value",)
    assert compute.outputs == ("doubled", "label")
    assert compute.demanded_by == ("record:doubled", "record:label")

    run = prepared.run()
    result = run.result(structured().output)
    [point] = result
    assert point.value(result.output.doubled) == 6
    assert point.value(result.output.label) == "value-3"


def test_host_unit_conversion_is_recordable_and_visible_in_preview(
    tmp_path: Path,
) -> None:
    def source_voltage() -> Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="V")),
    ]:
        return sc.Quantity(0.125, "V")

    @sc.experiment(id="test.session.converted-quantity")
    def converted(experiment: sc.ExperimentContext) -> _ConvertedQuantityResult:
        voltage = cast(
            "sc.ValueRef[sc.Quantity]",
            experiment.compute(fn=source_voltage),
        )
        return _ConvertedQuantityResult(
            voltage=experiment.convert(voltage, "mV"),
        )

    config = load_config()
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=ExperimentSystem(
            instrument_catalog=InstrumentContractCatalog(
                config_content_hash=config_content_hash(config)
            )
        ),
    )

    prepared = lab.prepare(converted())
    preview = prepared.preview()
    assert preview.host_compute_ids == ("source_voltage", "convert_unit_value")
    assert preview.observation_compute_ids == ()
    assert preview.computes[1].inputs == (
        "value",
        "source_unit",
        "target_unit",
    )

    result = prepared.run().result(converted().output)
    assert result[0].value(result.output.voltage) == sc.Quantity(125.0, "mV")


def test_measurement_batches_page_a_real_run_and_preserve_point_identity(
    tmp_path: Path,
) -> None:
    run = _run_signal_scan(tmp_path)

    batches = list(run.measurement_batches(batch_size=2))

    assert [len(batch) for batch in batches] == [2, 1]
    assert [record.point_index for batch in batches for record in batch.records] == [
        0,
        1,
        2,
    ]
    assert [batch.dims["point"] for batch in batches] == [2, 1]
    assert [batch.metadata["scopecat_batch_offset"] for batch in batches] == [0, 2]
    assert all(
        next(
            dimension.size
            for dimension in batch.schema.dimensions
            if dimension.id == "point"
        )
        == 3
        for batch in batches
    )
    assert tuple(batches[0].coords) == ("drive_frequency",)
    assert tuple(batches[0].data_vars) == ("signal",)
    with pytest.raises(ValueError, match="between 1 and 500"):
        run.measurement_batches(batch_size=0)
    with pytest.raises(ValueError, match="between 1 and 500"):
        run.measurement_batches(batch_size=501)


def test_empty_measurement_batches_yield_one_schema_bearing_dataset(
    tmp_path: Path,
) -> None:
    @sc.experiment(id="test.session.empty-points", kind="empty-points")
    def empty_points(experiment: sc.ExperimentContext) -> None:
        experiment.points((), coordinates=(DRIVE_FREQUENCY_POINT,))
        experiment.alias(DRIVE_FREQUENCY_POINT, record_id="observed_frequency")

    config = load_config()
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=ExperimentSystem(
            instrument_catalog=InstrumentContractCatalog(
                config_content_hash=config_content_hash(config)
            )
        ),
    )
    run = lab.prepare(empty_points).run()

    [batch] = run.measurement_batches(batch_size=2)

    assert batch.records == ()
    assert batch.dims["point"] == 0
    assert tuple(batch.coords) == ("drive_frequency",)
    assert tuple(batch.data_vars) == ("observed_frequency",)
    assert batch.metadata["scopecat_batch_offset"] == 0
    assert (
        next(
            dimension.size
            for dimension in batch.schema.dimensions
            if dimension.id == "point"
        )
        == 0
    )

    reader = cast(
        "_ArrowRecordBatchReader",
        run.measurement_record_batches(  # pyright: ignore[reportUnknownMemberType]
            columns={"frequency": "drive_frequency"},
            batch_size=2,
        ),
    )
    assert reader.schema.names == [
        "point_index",
        "logical_point_id",
        "frequency",
        "frequency__unavailable_reason",
    ]
    assert list(reader) == []


def test_measurement_batch_converts_directly_to_arrow(tmp_path: Path) -> None:
    [first, second] = _run_signal_scan(tmp_path).measurement_batches(batch_size=2)

    first_table = cast(
        "_ArrowTable",
        first.to_arrow(),  # pyright: ignore[reportUnknownMemberType]
    )
    second_table = cast(
        "_ArrowTable",
        second.to_arrow(),  # pyright: ignore[reportUnknownMemberType]
    )

    assert first_table.num_rows == 2
    assert second_table.num_rows == 1
    assert first_table["point_index"].to_pylist() == [0, 1]
    assert second_table["point_index"].to_pylist() == [2]


def test_run_projects_paged_measurements_into_one_arrow_reader(tmp_path: Path) -> None:
    run = _run_signal_scan(tmp_path)

    reader = cast(
        "_ArrowRecordBatchReader",
        run.measurement_record_batches(  # pyright: ignore[reportUnknownMemberType]
            columns={
                "frequency": "drive_frequency",
                "response": "signal",
            },
            batch_size=2,
        ),
    )
    batches = list(reader)

    assert reader.schema.names == [
        "point_index",
        "logical_point_id",
        "frequency",
        "frequency__unavailable_reason",
        "response",
        "response__unavailable_reason",
    ]
    assert [batch.num_rows for batch in batches] == [2, 1]
    assert all(batch.schema.names == reader.schema.names for batch in batches)
    assert [
        point for batch in batches for point in batch["point_index"].to_pylist()
    ] == [0, 1, 2]
    assert all(
        reason is None
        for batch in batches
        for reason in batch["response__unavailable_reason"].to_pylist()
    )


def _run_signal_scan(tmp_path: Path) -> RunHandle:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    return lab.prepare(load_invocation()).run()


def test_in_process_lab_closed_loop_uses_notebook_first_candidate_config(
    tmp_path: Path,
) -> None:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    experiment = load_invocation()

    baseline = lab.prepare(experiment).run()
    dataset = baseline.measurements()
    analysis = (
        baseline.analysis("manual best signal")
        .input("raw-measurements")
        .propose(
            "drive_frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                _quantity_coordinate(
                    dataset.records[2],
                    "drive_frequency",
                ),
            ),
            reason="manual notebook pick",
        )
    )
    outcome = analysis.save()
    candidate_config = outcome.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.id.startswith("run_")
    assert dataset.entry.id == "raw-measurements"
    assert [input_ref.target for input_ref in outcome.inputs] == ["raw-measurements"]
    assert not any(
        record.kind == "candidate_config" for record in baseline.manifest.records
    )
    assert candidate.manifest.status == "completed"
    source = candidate.manifest.config_source
    assert isinstance(source, AnalysisCandidateRunConfigSource)
    assert source.source_run_id == baseline.id
    assert source.analysis_record_id == outcome.record.id
    assert source.proposal_id == candidate_config.proposal_id


def test_in_process_provider_closed_loop_uses_candidate_config_shortcut(
    tmp_path: Path,
) -> None:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    experiment = load_invocation()

    baseline = lab.prepare(experiment).run()
    dataset = baseline.measurements()
    analysis = baseline.analysis("manual center point").propose(
        "drive_frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            _quantity_coordinate(
                dataset.records[2],
                "drive_frequency",
            ),
        ),
        reason="manual center point",
    )
    outcome = analysis.save()
    candidate_config = outcome.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.manifest.status == "completed"
    assert len(dataset.records) == 3
    assert dataset.entry.id == "raw-measurements"
    assert (
        candidate_config.parameter_proposal.deltas[0].parameter_id == "drive_frequency"
    )
    assert candidate.manifest.status == "completed"
    source = candidate.manifest.config_source
    assert isinstance(source, AnalysisCandidateRunConfigSource)
    assert source.analysis_record_id == outcome.record.id
