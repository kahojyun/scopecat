from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.sdk.instruments import (
    InstrumentDescription,
    interface,
    string_property,
)

_CONFIG_HASH = "sha256:" + ("0" * 64)


def _description(
    instrument_id: str,
    *,
    property_id: str = "label",
) -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id=instrument_id,
        implementation_id="tests.instrument",
        implementation_version="1",
        interfaces=[
            interface(
                "tests.instrument/v1",
                properties=[string_property(property_id)],
            )
        ],
    )


def test_instrument_contract_catalog_is_frozen_and_serializable() -> None:
    catalog = InstrumentContractCatalog(
        config_content_hash=_CONFIG_HASH,
        provider_id="tests.provider",
        instruments=(_description("source-0"),),
    )

    restored = InstrumentContractCatalog.model_validate_json(catalog.model_dump_json())

    assert restored == catalog
    assert catalog.model_config.get("frozen") is True


def test_instrument_contract_catalog_requires_provider_for_instruments() -> None:
    with pytest.raises(ValidationError, match="require a provider identity"):
        InstrumentContractCatalog(
            config_content_hash=_CONFIG_HASH,
            instruments=(_description("source-0"),),
        )


def test_instrument_contract_catalog_requires_unique_instruments() -> None:
    description = _description("source-0")

    with pytest.raises(ValidationError, match="unique instrument ids"):
        InstrumentContractCatalog(
            config_content_hash=_CONFIG_HASH,
            provider_id="tests.provider",
            instruments=(description, description),
        )


def test_instrument_contract_catalog_requires_stable_interface_specs() -> None:
    with pytest.raises(ValidationError, match="one stable specification"):
        InstrumentContractCatalog(
            config_content_hash=_CONFIG_HASH,
            provider_id="tests.provider",
            instruments=(
                _description("source-0"),
                _description("source-1", property_id="name"),
            ),
        )
