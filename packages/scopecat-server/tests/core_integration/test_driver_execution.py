from pathlib import Path

from scopecat.sdk.instruments import PropertyRef
from scopecat_testkit.instrument_drivers import SignalInstrumentDriver, load_config
from scopecat_testkit.server.execution import execute_bound_run
from scopecat_testkit.workflow_fixtures import load_experiment


def test_run_accepts_instrument_driver(tmp_path: Path) -> None:
    instrument = SignalInstrumentDriver()

    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert len(instrument.collect_requests) == 3
    assert [result.result_id for result in instrument.collect_requests[0].results] == [
        "signal"
    ]
    target = instrument.applied[0].entries[0].target
    assert isinstance(target, PropertyRef)
    assert target.interface_id == ("test.set_frequency/v1")
