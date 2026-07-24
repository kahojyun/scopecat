"""Application errors translated by the daemon transport."""


class BackendNotFound(RuntimeError):
    """The daemon application service could not resolve an object."""


class BackendConflict(RuntimeError):
    """The requested command conflicts with current durable state."""


__all__ = ["BackendConflict", "BackendNotFound"]
