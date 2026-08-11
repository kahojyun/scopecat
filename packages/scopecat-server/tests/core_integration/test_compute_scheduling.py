from pathlib import Path
from typing import Annotated

import scopecat as sc
from scopecat.sdk.instruments import (
    DriverPayload,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InterfaceRef,
)
from scopecat_testkit.instrument_drivers import SignalInstrumentDriver
from scopecat_testkit.instrument_host import compose_test_instruments
from scopecat_testkit.materialized_effects import config_with_physical_resources
from scopecat_testkit.payload_codecs import json_payload_codecs
from scopecat_testkit.server.in_process_lab import in_process_lab

_PLAY_PROGRAM = InterfaceRef("test.play_program/v1")
_PLAY_PROGRAM_PLAY = _PLAY_PROGRAM.operation("play")
_PLAY_PROGRAM_ARGUMENT = _PLAY_PROGRAM_PLAY.argument("program")

type _SourceProgramInput = Annotated[
    sc.Input[object],
    sc.ScalarType(sc.PayloadType("source_program")),
]


class _SingleDriverProvider:
    def __init__(self, driver: SignalInstrumentDriver) -> None:
        self.driver = driver

    @property
    def provider_id(self) -> str:
        return "tests.execution_characterization"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(self.driver.describe(),),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> SignalInstrumentDriver:
        assert context.binding.id == self.driver.instrument_id
        return self.driver


def test_project_run_schedules_parent_compute_before_child_consumer(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    source_program_type = sc.ScalarType(sc.PayloadType("source_program"))
    pulse_program_type = sc.ScalarType(sc.PayloadType("pulse_program"))

    def consume(*, program: object) -> dict[str, object]:
        calls.append("consume")
        return {"consumed": program}

    @sc.module(id="tests.compute_schedule.child")
    def child(
        context: sc.ModuleContext,
        program: _SourceProgramInput,
    ) -> None:
        consumed = context.compute(
            "consume-program",
            fn=consume,
            inputs={"program": sc.input_ref(program)},
            output_type=pulse_program_type,
        )
        source = context._resource("source", requires=(_PLAY_PROGRAM,))
        context._invoke(
            "play-program",
            resource=source,
            operation=_PLAY_PROGRAM_PLAY,
            arguments={_PLAY_PROGRAM_ARGUMENT: consumed},
        )

    def produce() -> dict[str, object]:
        calls.append("produce")
        return {"source": "parent"}

    @sc.module(id="tests.compute_schedule.parent")
    def parent(context: sc.ModuleContext) -> None:
        produced = context.compute(
            "produce-program",
            fn=produce,
            output_type=source_program_type,
        )
        context.use(
            child.instantiate(
                "compute-schedule-child",
                program=produced,
            )
        )

    @sc.experiment(id="tests.compute_schedule", kind="characterization")
    def experiment(experiment: sc.ExperimentContext) -> None:
        experiment.use(parent())

    driver = SignalInstrumentDriver()
    payload_codecs = json_payload_codecs("pulse_program")
    config = config_with_physical_resources({"source-0": ("test.play_program/v1",)})
    composition = compose_test_instruments(
        config=config,
        provider=_SingleDriverProvider(driver),
        payload_codecs=payload_codecs,
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    run = lab.prepare(experiment).run()

    assert run.manifest.status == "completed"
    assert calls == ["produce", "consume"]
    assert len(driver.invoked) == 1
    invoked = driver.invoked[0]
    [argument] = invoked.arguments.values()
    assert isinstance(argument, DriverPayload)
    assert argument.schema_id == "pulse_program"
    assert argument.value == {"consumed": {"source": "parent"}}
