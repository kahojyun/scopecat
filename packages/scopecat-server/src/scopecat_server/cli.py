"""Project-oriented Scopecat command line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Never

import typer
from rich.console import Console
from scopecat.project import ProjectManifestError, open_project

from .lifecycle import (
    DaemonLifecycleError,
    initialize_project,
    inspect_daemon,
    open_project_gui,
    serve_project,
    start_project,
    stop_project,
)

app = typer.Typer(
    name="scopecat",
    help="Manage one local Scopecat lab project.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)

_CURRENT_DIRECTORY = Path()
_DEFAULT_STATIC_DIR = Path(__file__).with_name("static")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _validate_host(value: str) -> str:
    if value not in _LOOPBACK_HOSTS:
        raise typer.BadParameter("must be a loopback host")
    return value


@app.command("init")
def init_command(
    project: Annotated[
        Path,
        typer.Argument(help="Directory to initialize."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Initialize a minimal lab project."""

    try:
        initialized = initialize_project(project)
    except DaemonLifecycleError as error:
        _fail(error)
    console.print(f"[green]initialized[/green] {initialized.root}")


@app.command()
def serve(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
    host: Annotated[
        str,
        typer.Option(help="Loopback listen address.", callback=_validate_host),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            help="Listen port; 0 selects an available port.",
            min=0,
            max=65535,
        ),
    ] = 0,
) -> None:
    """Run the project daemon in the foreground."""

    try:
        selected = open_project(project)
        serve_project(
            selected,
            host=host,
            port=port,
            static_dir=_DEFAULT_STATIC_DIR,
        )
    except (DaemonLifecycleError, ProjectManifestError, OSError) as error:
        _fail(error)


@app.command()
def start(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
    host: Annotated[
        str,
        typer.Option(help="Loopback listen address.", callback=_validate_host),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            help="Listen port; 0 selects an available port.",
            min=0,
            max=65535,
        ),
    ] = 0,
) -> None:
    """Start the project daemon in the background."""

    try:
        selected = open_project(project)
        record = start_project(selected, host=host, port=port)
    except (DaemonLifecycleError, ProjectManifestError, OSError) as error:
        _fail(error)
    console.print(
        f"[green]running[/green] {record.base_url} [dim](pid {record.pid})[/dim]"
    )


@app.command()
def stop(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Stop the project's recorded daemon process."""

    try:
        selected = open_project(project)
        previous = stop_project(selected)
    except (DaemonLifecycleError, ProjectManifestError, OSError) as error:
        _fail(error)
    if previous.state == "stale":
        console.print("[yellow]stale[/yellow] record removed")
    else:
        console.print("[green]stopped[/green]")


@app.command()
def status(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Show process identity and daemon health."""

    try:
        selected = open_project(project)
        observed = inspect_daemon(selected)
    except (ProjectManifestError, OSError) as error:
        _fail(error)

    if observed.state == "running" and observed.record is not None:
        console.print(
            f"[green]running[/green] {observed.record.base_url} "
            f"[dim](pid {observed.record.pid})[/dim]"
        )
        return
    if observed.state == "degraded" and observed.record is not None:
        console.print(
            f"[yellow]degraded[/yellow] {observed.record.base_url}: {observed.detail}"
        )
        return
    if observed.state == "stale":
        console.print(f"[yellow]stale[/yellow]: {observed.detail}")
        return
    console.print("[dim]stopped[/dim]")


@app.command("open")
def open_command(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Open the project GUI in the system browser."""

    try:
        selected = open_project(project)
        endpoint = open_project_gui(selected)
    except (DaemonLifecycleError, ProjectManifestError, OSError) as error:
        _fail(error)
    console.print(f"[green]opened[/green] {endpoint}")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Typer application."""

    app(
        args=None if argv is None else list(argv),
        prog_name="scopecat",
    )


def _fail(error: Exception) -> Never:
    error_console.print(f"[red]error:[/red] {error}")
    raise typer.Exit(code=1) from error


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
