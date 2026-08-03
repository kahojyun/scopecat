"""Validated connection options shared by the package manifest and provider."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConnectionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class NoConnectionOptions(ConnectionOptions):
    pass


class Gs200ConnectionOptions(ConnectionOptions):
    monitor_option: bool = False
    remote_sense: bool = False
    guard_enabled: bool = False


class E5080BConnectionOptions(ConnectionOptions):
    channel: int = Field(default=1, ge=1)
    measurement: int = Field(default=1, ge=1)


__all__ = [
    "ConnectionOptions",
    "E5080BConnectionOptions",
    "Gs200ConnectionOptions",
    "NoConnectionOptions",
]
