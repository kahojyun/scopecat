"""Read-only handoff package engineering prototype.

The prototype owns the read-only opener and exposes route-local projection
objects. That keeps the first prototype focused on module shape and user-facing
read actions without promoting a shared measurement-record domain model.
"""

from pathlib import Path

from scopecat.handoff.opener import open_handoff_package
from scopecat.handoff.package import HandoffPackage


def open_package(package_dir: str | Path) -> HandoffPackage:
    """Open a directory-shaped handoff package for read-only local use."""

    return open_handoff_package(Path(package_dir))
