"""Configuration linking and target-specific program materialization.

Linking closes a verified typed program against accepted configuration while
retaining a symbolic point domain. It deliberately does not choose a relation
backend, select local Python implementations, materialize points, or produce a
target artifact. Those are explicit decisions of a later lowering, allowing
the same successful linked plan to feed local or domain-specific targets.
"""

__all__: list[str] = []
