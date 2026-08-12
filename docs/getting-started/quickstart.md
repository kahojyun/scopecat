# Source preview quickstart

This walkthrough creates a local project and completes one durable run without
requiring laboratory hardware.

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js and pnpm when building the project console from source

Scopecat does not yet publish an end-user installation command. The commands
below run the locked source workspace and should be treated as a development
preview rather than a stable distribution workflow.

## Prepare the source checkout

From the repository root, install the locked Python workspace and build the GUI:

```sh
uv sync --locked
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
```

The GUI build is needed only once until its source changes.

## Create a project

```sh
uv run scopecat init ./my-lab
uv run scopecat config check ./my-lab
```

`init` creates ordinary version-controlled Python source. `config check`
evaluates and validates that bootstrap source without starting a daemon or
creating project state.

## Start Scopecat

```sh
uv run scopecat start ./my-lab --static-dir apps/scopecat-ui/dist
uv run scopecat status ./my-lab
uv run scopecat open ./my-lab
```

`start` selects an available loopback port and records it inside the project.
The GUI and notebook clients discover that same daemon from the project; no
fixed URL is required.

## Complete the first run

In another terminal, from the repository root, run:

```sh
uv run python ./my-lab/notebooks/01_first_run.py
```

The script prints the run ID and terminal status. In the project console, open
the **Runs** workspace and select **First run**. The run has no measurements,
but it exercises project discovery, admission, durable history, notebook/daemon
communication, and GUI inspection.

The workflow is complete when all of these statements are true:

- the script reports a terminal `completed` status and a run ID;
- **First run** appears in the project run history;
- reopening the project console still shows the same durable run;
- completing the workflow did not require copying a daemon URL or storage ID.

The exact navigation and presentation may change while the UI is evolving.
Failure to make the four outcomes above apparent is product feedback, even when
the underlying command exits successfully.

## Stop the daemon

```sh
uv run scopecat stop ./my-lab
```

Next, use the [reference lab tutorial](../tutorials/reference-lab.md) for virtual
instruments, measurement data, analysis, and quantum calibration, or read the
[project layout reference](../reference/project-layout.md) before adapting the
generated application.
