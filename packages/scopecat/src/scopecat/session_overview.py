"""Overview facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat.reporting import RunOverview

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunSession


@dataclass(frozen=True)
class OverviewHandle:
    session: RunSession
    overview: RunOverview
    markdown: str


__all__ = ["OverviewHandle"]
