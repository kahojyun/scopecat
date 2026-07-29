"""Serializable driver registration metadata."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

type InstrumentConnectionKind = Literal["virtual", "tcpip_socket"]
type _NonEmptyText = Annotated[str, Field(min_length=1)]


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DriverConnectionSpec(_CatalogModel):
    kind: InstrumentConnectionKind
    options_schema: dict[str, JsonValue]


class DriverSpec(_CatalogModel):
    driver_id: _NonEmptyText
    implementation_version: _NonEmptyText
    label: _NonEmptyText
    manufacturer: _NonEmptyText | None = None
    model: _NonEmptyText | None = None
    connections: tuple[DriverConnectionSpec, ...] = Field(min_length=1)

    @field_validator("connections")
    @classmethod
    def validate_connection_kinds(
        cls,
        connections: tuple[DriverConnectionSpec, ...],
    ) -> tuple[DriverConnectionSpec, ...]:
        kinds = tuple(connection.kind for connection in connections)
        if len(kinds) != len(set(kinds)):
            raise ValueError("driver connection kinds must be unique")
        return connections


class DriverCatalog(_CatalogModel):
    provider_id: _NonEmptyText
    drivers: tuple[DriverSpec, ...] = ()

    @field_validator("drivers")
    @classmethod
    def validate_driver_ids(
        cls,
        drivers: tuple[DriverSpec, ...],
    ) -> tuple[DriverSpec, ...]:
        driver_ids = tuple(driver.driver_id for driver in drivers)
        if len(driver_ids) != len(set(driver_ids)):
            raise ValueError("driver ids must be unique")
        return drivers

    def get(self, driver_id: str) -> DriverSpec | None:
        for driver in self.drivers:
            if driver.driver_id == driver_id:
                return driver
        return None


__all__ = [
    "DriverCatalog",
    "DriverConnectionSpec",
    "DriverSpec",
    "InstrumentConnectionKind",
]
