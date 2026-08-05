from __future__ import annotations

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
        experiment.record(signal, record_id="signal")

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


def test_in_process_lab_records_compute_value_without_instruments(
    tmp_path: Path,
) -> None:
    @sc.experiment(id="test.session.compute-only", kind="compute-only")
    def compute_only(experiment: sc.ExperimentContext) -> None:
        score = experiment.compute(
            "score",
            fn=lambda: 2.5,
            output_type=sc.ScalarType(sc.FloatType()),
        )
        experiment.record(score)

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

    run = lab.prepare(compute_only).run()
    dataset = run.measurements()

    assert run.manifest.status == "completed"
    assert isinstance(dataset, Dataset)
    assert dataset.entry.id == "raw-measurements"
    [record] = dataset.records
    assert record.observables["score"] == MeasurementScalar.create(
        dtype="float64",
        value=2.5,
    )
    variable = next(item for item in dataset.schema.variables if item.id == "score")
    assert variable.source_value_id == "score"
    content = run.data()
    assert content.datasets == ("raw-measurements",)
    assert content.dataset("raw-measurements") == dataset.entry


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
        experiment.record(DRIVE_FREQUENCY_POINT, record_id="observed_frequency")

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
    saved = analysis.save()
    candidate_config = analysis.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.id.startswith("run_")
    assert dataset.entry.id == "raw-measurements"
    assert [input_ref.target for input_ref in saved.inputs] == ["raw-measurements"]
    assert not any(
        record.kind == "candidate_config" for record in baseline.manifest.records
    )
    assert candidate.manifest.status == "completed"
    source = candidate.manifest.config_source
    assert isinstance(source, AnalysisCandidateRunConfigSource)
    assert source.source_run_id == baseline.id
    assert source.analysis_record_id == saved.record.id
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
    saved = analysis.save()
    candidate_config = analysis.candidate_config()
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
    assert source.analysis_record_id == saved.record.id
