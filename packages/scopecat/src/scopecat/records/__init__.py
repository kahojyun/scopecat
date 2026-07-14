"""Durable records persisted by Scopecat repositories and journals.

A structured run keeps operator intent, its accepted configuration snapshot,
the user-visible plan projection, and execution evidence as independently
readable records. The plan explains what was accepted but is not an executable
program. Transient authoring, compiler, planning, and runtime graphs never
become storage contracts or replay inputs.
"""

__all__: list[str] = []
