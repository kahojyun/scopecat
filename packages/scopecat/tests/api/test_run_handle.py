from __future__ import annotations

from pathlib import Path
from typing import Annotated

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.authoring import (
    ExperimentInvocation,
    ExperimentTemplate,
)
from scopecat.kernel.quantity import Quantity
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
    return simple_frequency_scan_template().bind(subject=subject)


def simple_frequency_scan_template() -> ExperimentTemplate[...]:
    def definition(
        experiment: authoring.ExperimentContext,
        subject: Annotated[
            authoring.Input[sc.EntityRef | str],
            authoring.EntityType(),
        ],
    ) -> None:
        del subject
        module_call = experiment.run(
            SIMPLE_FREQUENCY_SCAN(frequency=DRIVE_FREQUENCY_POINT)
        )
        experiment.scan(
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
        experiment.record(module_call.result, record_id="signal")

    return authoring.template(
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
    @sc.template(id="test.session.compute-only", kind="compute-only")
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
    raw = run.measurements().dataset

    assert run.manifest.status == "completed"
    [record] = raw.records
    assert record.observables["score"] == MeasurementScalar.create(
        dtype="float64",
        value=2.5,
    )
    variable = next(item for item in raw.dataset_schema.variables if item.id == "score")
    assert variable.source_value_id == "score"


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
    raw = baseline.measurements()
    analysis = (
        baseline.analysis("manual best signal")
        .input("raw-measurements")
        .propose(
            "drive_frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                _quantity_coordinate(
                    raw.dataset.records[2],
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
    assert raw.dataset_entry.id == "raw-measurements"
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
    raw = baseline.measurements()
    analysis = baseline.analysis("manual center point").propose(
        "drive_frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            _quantity_coordinate(
                raw.dataset.records[2],
                "drive_frequency",
            ),
        ),
        reason="manual center point",
    )
    saved = analysis.save()
    candidate_config = analysis.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.manifest.status == "completed"
    assert len(raw.dataset.records) == 3
    assert raw.dataset_entry.id == "raw-measurements"
    assert (
        candidate_config.parameter_proposal.deltas[0].parameter_id == "drive_frequency"
    )
    assert candidate.manifest.status == "completed"
    source = candidate.manifest.config_source
    assert isinstance(source, AnalysisCandidateRunConfigSource)
    assert source.analysis_record_id == saved.record.id
