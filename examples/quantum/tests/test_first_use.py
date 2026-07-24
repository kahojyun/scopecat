from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template


def test_cli_project_serves_gui_and_shared_notebook_run(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    """Exercise the documented project -> daemon -> GUI -> notebook path."""

    project = tmp_path / "quantum"
    project.mkdir()
    shutil.copy2(EXAMPLE_ROOT / "scopecat.toml", project / "scopecat.toml")
    shutil.copytree(EXAMPLE_ROOT / "config", project / "config")
    daemon_url = f"http://127.0.0.1:{free_tcp_port}"
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and argv
        [
            sys.executable,
            "-c",
            "import sys; from scopecat_server.cli import main; main(sys.argv[1:])",
            "serve",
            str(project),
            "--port",
            str(free_tcp_port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        index = _wait_for_text(f"{daemon_url}/")
        assert '<div id="root"></div>' in index
        script_match = re.search(r'<script[^>]+src="([^"]+)"', index)
        assert script_match is not None
        bundle = _wait_for_text(f"{daemon_url}{script_match.group(1)}")
        assert "Parameter proposals" in bundle
        assert "/api/v1/config-registry" in bundle

        with sc.open_project(project).connect(daemon_url) as lab:
            run = lab.prepare(readout_frequency_template(qubit="q0")).run(
                name="first-use smoke",
                tags=("first-use",),
            )

        with sc.connect(daemon_url) as observer:
            detail = observer.get_run(run.id)

        assert detail.manifest.status == "completed"
        assert detail.control.admission.request is not None
        assert detail.control.admission.request.metadata["name"] == "first-use smoke"
        assert detail.control.admission.request.metadata["tags"] == ["first-use"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _wait_for_text(url: str) -> str:
    deadline = time.monotonic() + 15
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1)
            response.raise_for_status()
            return response.text
        except (OSError, httpx.HTTPError) as error:
            last_error = error
            time.sleep(0.05)
    raise RuntimeError(f"daemon did not become ready: {last_error}")
