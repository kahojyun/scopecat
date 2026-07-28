"""Serializable instrument contracts resolved for one config snapshot."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import Problem
from scopecat.records.config import ConfigContentHash
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    validate_instrument_description_collection,
)


class InstrumentContractCatalog(BaseModel):
    """Daemon-advertised contracts consumed by planning without live drivers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_content_hash: ConfigContentHash
    provider_id: str | None = Field(default=None, min_length=1)
    instruments: tuple[InstrumentDescription, ...] = ()
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_catalog(self) -> InstrumentContractCatalog:
        if self.provider_id is None and self.instruments:
            raise ValueError("instrument contracts require a provider identity")
        validate_instrument_description_collection(self.instruments)
        return self


__all__ = ["InstrumentContractCatalog"]
