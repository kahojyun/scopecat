"""Project-oriented Scopecat command line."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Never

import httpx2
import typer
from rich.console import Console
from scopecat.config.resolution import validate_config_profile
from scopecat.kernel.errors import ScopecatError
from scopecat.project import ProjectManifestError, open_project
from scopecat.records.config import config_content_hash

from .config_commands import (
    apply_project_config,
    diff_project_config,
    export_project_config,
)
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
config_app = typer.Typer(
    help="Inspect project configuration sources.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
console = Console()
error_console = Console(stderr=True)

_CURRENT_DIRECTORY = Path()
_DEFAULT_STATIC_DIR = Path(__file__).with_name("static")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_PROJECT_CONFIG_ERRORS = (
    ScopecatError,
    ProjectManifestError,
    httpx2.HTTPError,
    ImportError,
    AttributeError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


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
    """Initialize a runnable local lab project."""

    try:
        initialized = initialize_project(project)
    except DaemonLifecycleError as error:
        _fail(error)
    console.print(
        f"[green]initialized[/green] {initialized.root}",
        soft_wrap=True,
    )
    console.print(
        f"[dim]config source[/dim] "
        f"{initialized.root / 'src/scopecat_lab/configuration.py'}",
        soft_wrap=True,
    )
    project_arg = shlex.quote(str(initialized.root))
    notebook_arg = shlex.quote(str(initialized.root / "notebooks/01_first_run.py"))
    console.print(
        f"[dim]next[/dim] scopecat config check {project_arg}",
        soft_wrap=True,
    )
    console.print(
        f"[dim]next[/dim] scopecat start {project_arg}",
        soft_wrap=True,
    )
    console.print(
        f"[dim]next[/dim] scopecat open {project_arg}",
        soft_wrap=True,
    )
    console.print(
        f"[dim]first run[/dim] python {notebook_arg}",
        soft_wrap=True,
    )


@config_app.command("check")
def config_check(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Validate the application's lazy bootstrap configuration source."""

    try:
        selected = open_project(project)
        bootstrap_config = selected.load_application().bootstrap_config
        if bootstrap_config is None:
            raise ValueError("project application does not define bootstrap_config")
        result = validate_config_profile(bootstrap_config())
    except _PROJECT_CONFIG_ERRORS as error:
        _fail(error)

    console.print(
        f"[green]valid[/green] snapshot={result.config.id} "
        f"content_hash={config_content_hash(result.config)} "
        f"warnings={len(result.problems)}",
        soft_wrap=True,
    )


@config_app.command("diff")
def config_diff(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
) -> None:
    """Compare executable project configuration with the daemon default."""

    try:
        result = diff_project_config(open_project(project))
    except _PROJECT_CONFIG_ERRORS as error:
        _fail(error)

    if not result.has_drift:
        console.print(
            f"[green]in sync[/green] content_hash={result.source_content_hash}",
            soft_wrap=True,
        )
        return

    console.print(
        f"[yellow]different[/yellow] source={result.source_content_hash} "
        f"daemon={result.active_content_hash}",
        soft_wrap=True,
    )
    for line in result.unified_json_diff():
        console.print(line, markup=False, soft_wrap=True)


@config_app.command("apply")
def config_apply(
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
    actor: Annotated[
        str,
        typer.Option(help="Identity recorded for registration and activation."),
    ] = "local-operator",
    note: Annotated[
        str,
        typer.Option(help="Reason recorded with the immutable revision."),
    ] = "apply project config source",
) -> None:
    """Validate project configuration and make it the daemon default."""

    try:
        result = apply_project_config(
            open_project(project),
            actor=actor,
            note=note,
        )
    except _PROJECT_CONFIG_ERRORS as error:
        _fail(error)

    state = "[green]applied[/green]" if result.changed else "[green]in sync[/green]"
    console.print(
        f"{state} entry={result.receipt.entry.id} "
        f"content_hash={result.source_content_hash}",
        soft_wrap=True,
    )


@config_app.command("export")
def config_export(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Destination JSON snapshot."),
    ],
    project: Annotated[
        Path,
        typer.Argument(help="Project directory or scopecat.toml."),
    ] = _CURRENT_DIRECTORY,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing destination."),
    ] = False,
) -> None:
    """Export the complete daemon default as generated JSON."""

    try:
        result = export_project_config(
            open_project(project),
            output,
            overwrite=force,
        )
    except _PROJECT_CONFIG_ERRORS as error:
        _fail(error)

    console.print(
        f"[green]exported[/green] {result.destination} "
        f"content_hash={result.content_hash}",
        soft_wrap=True,
    )


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
    static_dir: Annotated[
        Path | None,
        typer.Option(help="Generated GUI bundle to serve."),
    ] = None,
    api_only: Annotated[
        bool,
        typer.Option(help="Serve the API without the project GUI."),
    ] = False,
) -> None:
    """Run the project daemon in the foreground."""

    try:
        selected = open_project(project)
        selected_static_dir = _select_static_dir(
            static_dir=static_dir,
            api_only=api_only,
        )
        serve_project(
            selected,
            host=host,
            port=port,
            static_dir=selected_static_dir,
        )
    except (DaemonLifecycleError, ProjectManifestError, OSError, ValueError) as error:
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
    static_dir: Annotated[
        Path | None,
        typer.Option(help="Generated GUI bundle to serve."),
    ] = None,
    api_only: Annotated[
        bool,
        typer.Option(help="Start the daemon without the project GUI."),
    ] = False,
) -> None:
    """Start the project daemon in the background."""

    try:
        selected = open_project(project)
        selected_static_dir = _select_static_dir(
            static_dir=static_dir,
            api_only=api_only,
        )
        record = start_project(
            selected,
            host=host,
            port=port,
            static_dir=selected_static_dir,
        )
    except (DaemonLifecycleError, ProjectManifestError, OSError, ValueError) as error:
        _fail(error)
    console.print(
        f"[green]running[/green] {record.base_url} [dim](pid {record.pid})[/dim]"
    )


def _select_static_dir(
    *,
    static_dir: Path | None,
    api_only: bool,
) -> Path | None:
    if api_only:
        if static_dir is not None:
            raise ValueError("--api-only and --static-dir cannot be used together")
        return None
    selected = _DEFAULT_STATIC_DIR if static_dir is None else static_dir.resolve()
    if not (selected / "index.html").is_file():
        raise ValueError(
            "GUI bundle is not installed; pass its directory with --static-dir "
            "or use --api-only"
        )
    return selected


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
    error_console.print(
        f"[red]error:[/red] {error}",
        soft_wrap=True,
    )
    raise typer.Exit(code=1) from error


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
