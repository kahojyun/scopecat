"""Explicit operator intents for destructive instrument inventory changes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type _NonEmptyText = Annotated[str, Field(min_length=1)]


class _InventoryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstrumentInventoryRemoval(_InventoryIntent):
    kind: Literal["remove"] = "remove"
    instrument_id: _NonEmptyText
    exclusivity_key: _NonEmptyText


class InstrumentInventoryRekey(_InventoryIntent):
    kind: Literal["rekey"] = "rekey"
    instrument_id: _NonEmptyText
    from_exclusivity_key: _NonEmptyText
    to_exclusivity_key: _NonEmptyText

    @model_validator(mode="after")
    def validate_key_change(self) -> InstrumentInventoryRekey:
        if self.from_exclusivity_key == self.to_exclusivity_key:
            raise ValueError("inventory rekey must change the exclusivity key")
        return self


class InstrumentInventoryRenameRekey(_InventoryIntent):
    kind: Literal["rename_rekey"] = "rename_rekey"
    from_instrument_id: _NonEmptyText
    to_instrument_id: _NonEmptyText
    from_exclusivity_key: _NonEmptyText
    to_exclusivity_key: _NonEmptyText

    @model_validator(mode="after")
    def validate_identity_change(self) -> InstrumentInventoryRenameRekey:
        if self.from_instrument_id == self.to_instrument_id:
            raise ValueError("inventory rename must change the instrument id")
        if self.from_exclusivity_key == self.to_exclusivity_key:
            raise ValueError("inventory rename-rekey must change the exclusivity key")
        return self


type InstrumentInventoryChange = Annotated[
    InstrumentInventoryRemoval
    | InstrumentInventoryRekey
    | InstrumentInventoryRenameRekey,
    Field(discriminator="kind"),
]


__all__ = [
    "InstrumentInventoryChange",
    "InstrumentInventoryRekey",
    "InstrumentInventoryRemoval",
    "InstrumentInventoryRenameRekey",
]
