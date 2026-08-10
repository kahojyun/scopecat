"""Small presentation helpers for executable notebook recipes."""

from __future__ import annotations

from pprint import pprint


def show(value: object) -> None:
    """Render a value readably in both notebook cells and terminal runs."""
    pprint(value, sort_dicts=False)
