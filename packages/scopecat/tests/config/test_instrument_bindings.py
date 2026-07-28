from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.records.config import (
    instrument_bindings,
)
from scopecat.sdk.instruments import InstrumentBindingSpec
from tests.testkit.workflow_fixtures import load_config


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
