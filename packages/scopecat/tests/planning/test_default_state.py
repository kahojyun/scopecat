from __future__ import annotations

from dataclasses import dataclass
from typing import Never

import pytest
from pydantic import ValidationError

from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.provider_binding import (
    resolve_instrument_contract_catalog,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentRunStartPolicy,
    InstrumentSpec,
    config_content_hash,
)
from scopecat.records.instrument import InstrumentPropertyState
from scopecat.sdk.instruments import (
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    discriminated_state,
    enum_property,
    interface,
    quantity_property,
    state_case,
    string_property,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config


def test_default_state_requires_unique_property_targets() -> None:
    property_state = InstrumentPropertyState(
        interface_id="test.set_frequency/v1",
        property_id="frequency",
        value=StateValue(Quantity(5.0, "GHz")),
    )

    with pytest.raises(ValidationError, match="property targets must be unique"):
        InstrumentSpec.model_validate(
            {
                **_instrument_spec_data(),
                "default_state": [property_state, property_state],
                "run_start": "preserve",
            }
        )


def test_instrument_spec_requires_an_explicit_run_start_policy() -> None:
    with pytest.raises(ValidationError, match="run_start"):
        InstrumentSpec.model_validate(_instrument_spec_data())


def test_apply_default_state_requires_declared_defaults() -> None:
    with pytest.raises(ValidationError, match="non-empty default state"):
        InstrumentSpec.model_validate(
            {
                **_instrument_spec_data(),
                "run_start": "apply_default_state",
            }
        )


def test_catalog_resolution_validates_defaults_against_advertised_interface() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(5.0, "GHz")),
            ),
        ),
        TestSignalInstrumentProvider(),
    )

    assert result.problems == ()


def test_catalog_validates_preserved_default_state_independently() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="missing",
                value=StateValue(Quantity(5.0, "GHz")),
            ),
            run_start="preserve",
        ),
        TestSignalInstrumentProvider(),
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
        "default_state",
    )


def test_case_local_default_requires_explicit_discriminator() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.mode/v1",
                property_id="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            ),
        ),
        _ModeProvider(),
    )

    assert [issue.code for issue in result.problems] == [
        "instrument_driver_state_case_unknown"
    ]


def test_explicit_discriminator_requires_a_complete_default_case() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.mode/v1",
                property_id="mode",
                value=StateValue("voltage"),
            ),
        ),
        _ModeProvider(),
    )

    assert [issue.code for issue in result.problems] == [
        "instrument_driver_state_case_incomplete"
    ]


def test_complete_explicit_case_default_is_authoritative() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
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
        ),
        _ModeProvider(),
    )

    assert result.problems == ()


def test_default_state_requires_an_advertised_description() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(5.0, "GHz")),
            ),
            run_start="preserve",
        ),
        _EmptyProvider(),
    )

    assert [issue.code for issue in result.problems] == [
        "instrument_default_state_description_missing"
    ]


def test_default_state_rejects_write_only_properties() -> None:
    result = _resolve_catalog(
        _config_with_default_state(
            InstrumentPropertyState(
                interface_id="test.secret/v1",
                property_id="token",
                value=StateValue("configured"),
            ),
            run_start="preserve",
        ),
        _WriteOnlyProvider(),
    )

    [issue] = result.problems
    assert issue.code == "instrument_driver_write_only_property"
    assert issue.phase == ProblemPhase.PROVIDER_PREFLIGHT
    assert issue.location == model_location(
        "config",
        "system",
        "instrument_registry",
        "instruments",
        0,
        "default_state",
    )


def test_catalog_resolution_records_description_failure() -> None:
    config = load_config()

    result = _resolve_catalog(config, _FailingProvider())

    assert result.config_content_hash == config_content_hash(config)
    assert result.provider_id == _FailingProvider.provider_id
    assert result.instruments == ()
    assert [issue.code for issue in result.problems] == [
        "instrument_provider_description_failed"
    ]


def _resolve_catalog(
    config: ConfigProfileSnapshot,
    provider: InstrumentProvider,
) -> InstrumentContractCatalog:
    return resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )


def _config_with_default_state(
    *properties: InstrumentPropertyState,
    run_start: InstrumentRunStartPolicy = "apply_default_state",
) -> ConfigProfileSnapshot:
    config = load_config()
    configured = config.instrument_registry.instruments[0]
    instrument = InstrumentSpec(
        id=configured.id,
        exclusivity_key=configured.exclusivity_key,
        driver_id=configured.driver_id,
        connection=configured.connection.model_copy(deep=True),
        default_state=[item.model_copy(deep=True) for item in properties],
        run_start=run_start,
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


def _instrument_spec_data() -> dict[str, object]:
    return {
        "id": "source",
        "exclusivity_key": "source",
        "driver_id": "tests.source",
        "connection": {"kind": "virtual"},
    }


@dataclass(frozen=True)
class _ModeProvider:
    provider_id: str = "tests.mode_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        instrument_id = context.bindings[0].id
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
                            state=discriminated_state(
                                enum_property(
                                    "mode",
                                    choices=("voltage", "current"),
                                ),
                                cases=(
                                    state_case(
                                        "voltage",
                                        properties=(
                                            quantity_property(
                                                "voltage_level",
                                                unit="V",
                                            ),
                                        ),
                                    ),
                                    state_case(
                                        "current",
                                        properties=(
                                            quantity_property(
                                                "current_level",
                                                unit="A",
                                            ),
                                        ),
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
class _WriteOnlyProvider:
    provider_id: str = "tests.write_only_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                InstrumentDescription(
                    instrument_id=context.bindings[0].id,
                    implementation_id="tests.write_only",
                    implementation_version="v1",
                    interfaces=[
                        interface(
                            "test.secret/v1",
                            properties=[
                                string_property("token", access="write_only"),
                            ],
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


@dataclass(frozen=True)
class _FailingProvider:
    provider_id: str = "tests.failing_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        raise RuntimeError("description failed")

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        raise AssertionError("catalog resolution must not connect an instrument")
