"""Read-only handoff package operations.

This module owns the read-only opener and exposes route-local projection
objects for user-facing read actions.
"""

from pathlib import Path

from scopecat.handoff.opener import open_handoff_package
from scopecat.handoff.package import HandoffPackage


def open_package(package_dir: str | Path) -> HandoffPackage:
    """Open a directory-shaped handoff package for read-only local use."""

    return open_handoff_package(Path(package_dir))
