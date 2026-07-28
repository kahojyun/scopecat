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
from scopecat.records.run import AnalysisCandidateRunConfigSource
from tests.testkit.authoring import DRIVE_FREQUENCY_POINT
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.instrument_host import compose_test_instruments
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation

SIMPLE_FREQUENCY_SCAN = (
    authoring.module_body(id="test.session.simple_frequency_scan")
    .resource("source", requires=("test.set_frequency/v1", "test.scalar_signal/v1"))
    .bind_property(
        "source",
        interface="test.set_frequency/v1",
        property="frequency",
        value=DRIVE_FREQUENCY_POINT,
    )
    .product("signal", unit="ratio")
    .acquire(
        "read-signal",
        "signal",
        resource="source",
        interface="test.scalar_signal/v1",
        acquisition="sample",
    )
    .build()
)


def simple_frequency_scan(*, subject: str) -> ExperimentInvocation:
    return simple_frequency_scan_template().bind(subject=subject)


def simple_frequency_scan_template() -> ExperimentTemplate[...]:
    def definition(
        subject: Annotated[
            authoring.Input[sc.EntityRef | str],
            authoring.EntityType(),
        ],
    ) -> authoring.ExperimentBody:
        del subject
        module_call = SIMPLE_FREQUENCY_SCAN()
        return (
            authoring.experiment(module_call)
            .scan(
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
            .record_product(module_call.products.signal, record_id="signal")
        )

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
                raw.dataset.records[2].coordinates["drive_frequency"],
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
            raw.dataset.records[2].coordinates["drive_frequency"],
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
