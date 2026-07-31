"""Transient, one-way compiler stages and their semantic foundations.

Authoring structure is lowered into backend-neutral semantic and typed graphs,
then bound to accepted configuration before any target-specific
materialization. A lower stage may retain explicit provenance, but must not
recover meaning from display names or depend on public authoring handles.

Compiler stage values are frozen, trusted in-process state. Constructors and
named verification or binding passes establish their invariants once; later
stages do not repeatedly validate the whole graph. Validation resumes when
independently produced provider data, effect results, or persisted bytes cross
back into core. None of these compiler values is a durable replay format.
"""

__all__: list[str] = []
