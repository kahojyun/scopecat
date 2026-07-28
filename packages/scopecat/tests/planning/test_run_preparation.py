from __future__ import annotations

from dataclasses import dataclass
from typing import Never

import pytest
from pydantic import ValidationError

from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.planning.provider_binding import preflight_instrument_provider
from scopecat.records.config import (
    ApplyDefaultsRunPreparation,
    ConfigProfileSnapshot,
    InstrumentSpec,
)
from scopecat.records.instrument import InstrumentPropertyState
from scopecat.sdk.instruments import (
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    discriminated_state,
    enum_property,
    interface,
    quantity_property,
    state_case,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config


def test_apply_defaults_requires_unique_non_empty_property_targets() -> None:
    property_state = InstrumentPropertyState(
        interface_id="test.set_frequency/v1",
        property_id="frequency",
        value=StateValue(Quantity(5.0, "GHz")),
    )

    with pytest.raises(ValidationError, match="at least 1 item"):
        ApplyDefaultsRunPreparation(properties=[])
    with pytest.raises(ValidationError, match="property targets must be unique"):
        ApplyDefaultsRunPreparation(properties=[property_state, property_state])


def test_instrument_spec_requires_an_explicit_run_preparation_policy() -> None:
    with pytest.raises(ValidationError, match="run_preparation"):
        InstrumentSpec.model_validate(
            {
                "id": "source",
                "driver_id": "tests.source",
                "connection": {"kind": "virtual"},
            }
        )


def test_provider_preflight_validates_defaults_against_advertised_interface() -> None:
    preparation = ApplyDefaultsRunPreparation(
        properties=[
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(5.0, "GHz")),
            )
        ]
    )

    result = preflight_instrument_provider(
        config=_config_with_preparation(preparation),
        instrument_provider=TestSignalInstrumentProvider(),
    )

    assert result.problems == ()


def test_provider_preflight_reports_invalid_default_at_config_policy() -> None:
    preparation = ApplyDefaultsRunPreparation(
        properties=[
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="missing",
                value=StateValue(Quantity(5.0, "GHz")),
            )
        ]
    )

    result = preflight_instrument_provider(
        config=_config_with_preparation(preparation),
        instrument_provider=TestSignalInstrumentProvider(),
    )

    [issue] = result.problems
    assert issue.code == "instrument_driver_unsupported_property"
    assert issue.phase == ProblemPhase.PROVIDER_PREFLIGHT
    assert issue.location == model_location(
        "config",
        "system",
        "instrument_registry",
        "instruments",
        0,
        "run_preparation",
    )


def test_case_local_default_requires_explicit_discriminator() -> None:
    preparation = ApplyDefaultsRunPreparation(
        properties=[
            InstrumentPropertyState(
                interface_id="test.mode/v1",
                property_id="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            )
        ]
    )

    result = preflight_instrument_provider(
        config=_config_with_preparation(preparation),
        instrument_provider=_ModeProvider(),
    )

    assert [issue.code for issue in result.problems] == [
        "instrument_driver_state_case_unknown"
    ]


def test_explicit_discriminator_makes_case_local_default_authoritative() -> None:
    preparation = ApplyDefaultsRunPreparation(
        properties=[
            InstrumentPropertyState(
                interface_id="test.mode/v1",
                property_id="mode",
                value=StateValue("voltage"),
            ),
            InstrumentPropertyState(
                interface_id="test.mode/v1",
                property_id="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            ),
        ]
    )

    result = preflight_instrument_provider(
        config=_config_with_preparation(preparation),
        instrument_provider=_ModeProvider(),
    )

    assert result.problems == ()


def test_apply_defaults_requires_an_advertised_description() -> None:
    preparation = ApplyDefaultsRunPreparation(
        properties=[
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(5.0, "GHz")),
            )
        ]
    )

    result = preflight_instrument_provider(
        config=_config_with_preparation(preparation),
        instrument_provider=_EmptyProvider(),
    )

    assert [issue.code for issue in result.problems] == [
        "instrument_run_preparation_description_missing"
    ]


def _config_with_preparation(
    preparation: ApplyDefaultsRunPreparation,
) -> ConfigProfileSnapshot:
    config = load_config()
    instrument = config.instrument_registry.instruments[0].model_copy(
        update={"run_preparation": preparation},
        deep=True,
    )
    registry = config.instrument_registry.model_copy(
        update={"instruments": [instrument]},
        deep=True,
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        },
        deep=True,
    )


@dataclass(frozen=True)
class _ModeProvider:
    provider_id: str = "tests.mode_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        instrument_id = context.config.instrument_registry.instruments[0].id
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                InstrumentDescription(
                    instrument_id=instrument_id,
                    implementation_id="tests.mode",
                    implementation_version="v1",
                    interfaces=[
                        interface(
                            "test.mode/v1",
                            properties=[
                                enum_property(
                                    "mode",
                                    choices=("voltage", "current"),
                                ),
                                quantity_property("voltage_level", unit="V"),
                                quantity_property("current_level", unit="A"),
                            ],
                            state=discriminated_state(
                                "mode",
                                cases=(
                                    state_case(
                                        "voltage",
                                        property_ids=("voltage_level",),
                                    ),
                                    state_case(
                                        "current",
                                        property_ids=("current_level",),
                                    ),
                                ),
                            ),
                        )
                    ],
                ),
            ),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        raise AssertionError("preflight must not connect an instrument")


@dataclass(frozen=True)
class _EmptyProvider:
    provider_id: str = "tests.empty_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(provider_id=self.provider_id)

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        raise AssertionError("preflight must not connect an instrument")
