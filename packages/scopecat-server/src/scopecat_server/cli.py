"""Command-line entry point for the local workspace daemon."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast

import uvicorn

from .project import discover_lab_project
from .runtime import LabApplicationFactory, LocalDaemonRuntime


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    project = discover_lab_project(args.project)
    application_spec = args.application or project.application
    runtime = LocalDaemonRuntime(
        project.root,
        application_factory=(
            None
            if application_spec is None
            else _load_application_factory(application_spec)
        ),
        bootstrap_config=args.bootstrap_config or project.bootstrap_config,
    )
    try:
        uvicorn.run(
            runtime.app(static_dir=args.ui_dir),
            host=args.host,
            port=args.port,
        )
    finally:
        runtime.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scopecatd",
        description="Run the Scopecat daemon for one local lab project.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="project directory or scopecat.toml (default: discover from cwd)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        choices=("127.0.0.1", "::1", "localhost"),
        help="listen address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="listen port (default: 8765)",
    )
    parser.add_argument(
        "--application",
        default=None,
        help="override the MODULE:CALLABLE LabApplication factory",
    )
    parser.add_argument(
        "--bootstrap-config",
        type=Path,
        default=None,
        help="seed config used only when the project registry is empty",
    )
    parser.add_argument(
        "--ui-dir",
        type=Path,
        default=Path(__file__).with_name("static"),
        help="built GUI directory containing index.html",
    )
    return parser


@dataclass(frozen=True, slots=True)
class _Arguments:
    project: Path
    host: str
    port: int
    application: str | None
    bootstrap_config: Path | None
    ui_dir: Path | None


def _parse_args(argv: Sequence[str] | None) -> _Arguments:
    parsed = _parser().parse_args(argv)
    return _Arguments(
        project=cast("Path", parsed.project),
        host=cast("str", parsed.host),
        port=cast("int", parsed.port),
        application=cast("str | None", parsed.application),
        bootstrap_config=cast("Path | None", parsed.bootstrap_config),
        ui_dir=cast("Path | None", parsed.ui_dir),
    )


def _load_application_factory(spec: str) -> LabApplicationFactory:
    module_name, separator, attribute_name = spec.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("lab application must use MODULE:CALLABLE")
    return cast(
        "LabApplicationFactory",
        getattr(import_module(module_name), attribute_name),
    )


__all__ = ["main"]
