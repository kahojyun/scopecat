"""Internal access to effect bundles held by workspace facade objects."""

from __future__ import annotations

from typing import cast

from scopecat.application.services import WorkspaceServices


def workspace_services(owner: object) -> WorkspaceServices:
    """Return the private service bundle for an internal facade collaborator."""

    return cast("WorkspaceServices", object.__getattribute__(owner, "_services"))


__all__ = ["workspace_services"]
