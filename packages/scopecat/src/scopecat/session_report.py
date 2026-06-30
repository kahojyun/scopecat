"""Report facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat.reporting import ReportJob, RunReport

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunSession


@dataclass(frozen=True)
class ReportHandle:
    session: RunSession
    job: ReportJob
    report: RunReport


__all__ = ["ReportHandle"]
