from __future__ import annotations

import scopecat_quantum as sq
from scopecat_quantum import authoring


def test_public_surface_only_exports_authoring() -> None:
    assert sq.__all__ == ["authoring"]
    assert sq.authoring is authoring
