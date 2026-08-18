# Command-line interface

The `scopecat` command manages one local lab project. Every command accepts a
project directory or a path to `scopecat.toml`; the current directory is the
default.

## Project lifecycle

| Command | Purpose |
| --- | --- |
| `scopecat init [PROJECT]` | Initialize a runnable project without replacing existing files. |
| `scopecat start [PROJECT]` | Start the daemon in the background. |
| `scopecat serve [PROJECT]` | Run the daemon in the foreground. |
| `scopecat status [PROJECT]` | Show recorded process identity and daemon health. |
| `scopecat open [PROJECT]` | Open the running project GUI. |
| `scopecat stop [PROJECT]` | Stop the project's recorded daemon process. |

`start` and `serve` accept `--host`, `--port`, `--static-dir`, and `--api-only`.
Only loopback hosts are accepted. Port `0`, the default, selects an available
port.

## Configuration

| Command | Purpose |
| --- | --- |
| `scopecat config check [PROJECT]` | Validate executable bootstrap source without creating state. |
| `scopecat config diff [PROJECT]` | Compare freshly evaluated source with the daemon default. |
| `scopecat config apply [PROJECT]` | Validate and publish the source as a new daemon default. |
| `scopecat config export [PROJECT] --output PATH` | Export the complete daemon default as JSON. |

`config apply` accepts `--actor` and `--note`. `config export` refuses to replace
an existing destination unless `--force` is supplied.

## Procedures

| Command | Purpose |
| --- | --- |
| `scopecat procedures work [PROJECT]` | Run the project-owned resident procedure planner and worker. |
| `scopecat procedures work [PROJECT] --once` | Plan, materialize, and dispatch one bounded cycle, then exit. |

The resident worker loads the project's exact procedure registry in its own
process and turns latest-only fixed UTC interval occurrences into ordinary exact
one-shot schedules; the daemon never executes user-authored procedure closures.
`--poll-seconds` controls the idle polling interval.

Use `scopecat COMMAND --help` as the authority for all current options. See the
[configuration how-to](../how-to/manage-configuration.md) for the intended
review workflow.
