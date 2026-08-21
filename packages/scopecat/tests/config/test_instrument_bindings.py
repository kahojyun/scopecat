from __future__ import annotations

import pytest
from pydantic import ValidationError
from scopecat_testkit.workflow_fixtures import load_config

from scopecat.records.config import (
    DriverManagedInstrumentConnection,
    InstrumentRegistry,
    InstrumentSpec,
    instrument_bindings,
)
from scopecat.sdk.instruments import InstrumentBindingSpec


def test_instrument_bindings_project_only_provider_inputs() -> None:
    config = load_config()
    [instrument] = config.instrument_registry.instruments

    [binding] = instrument_bindings(config)

    assert binding == InstrumentBindingSpec(
        id=instrument.id,
        driver_id=instrument.driver_id,
        connection=instrument.connection,
    )
    assert binding.connection is not instrument.connection
    assert set(binding.model_dump()) == {"id", "driver_id", "connection"}


def test_instrument_binding_is_frozen() -> None:
    [binding] = instrument_bindings(load_config())

    with pytest.raises(ValidationError, match="frozen"):
        binding.id = "replacement"


def test_instrument_spec_parses_driver_managed_connection_options() -> None:
    instrument = load_config().instrument_registry.instruments[0]
    parsed = InstrumentSpec.model_validate(
        {
            **instrument.model_dump(),
            "connection": {
                "kind": "driver_managed",
                "options": {"boxes": {"box0": "192.0.2.1"}},
            },
        }
    )

    assert parsed.connection == DriverManagedInstrumentConnection(
        options={"boxes": {"box0": "192.0.2.1"}}
    )


def test_instrument_exclusivity_key_is_required_and_non_empty() -> None:
    instrument = load_config().instrument_registry.instruments[0]
    data = instrument.model_dump(exclude={"exclusivity_key"})

    with pytest.raises(ValidationError, match="exclusivity_key"):
        InstrumentSpec.model_validate(data)
    with pytest.raises(ValidationError, match="at least 1 character"):
        InstrumentSpec.model_validate({**data, "exclusivity_key": ""})


def test_instrument_registry_rejects_shared_exclusivity_key() -> None:
    instrument = load_config().instrument_registry.instruments[0]
    alias = instrument.model_copy(update={"id": "source-alias"})

    with pytest.raises(ValidationError, match="exclusivity keys must be unique"):
        InstrumentRegistry(instruments=[instrument, alias])
