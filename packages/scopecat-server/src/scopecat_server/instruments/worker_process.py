"""Minimal multiprocessing entry point for an instrument worker."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast


def run_instrument_worker(
    connection: object,
    project_root: str,
    instrument_backend_spec: str,
) -> None:
    """Load the driver RPC runtime only after the spawned process is ready."""

    worker = import_module("scopecat_server.instruments.worker")
    worker_main = cast(
        "Callable[[object, str, str], None]",
        worker._instrument_worker_main,
    )
    worker_main(
        connection,
        project_root,
        instrument_backend_spec,
    )


__all__ = ["run_instrument_worker"]
