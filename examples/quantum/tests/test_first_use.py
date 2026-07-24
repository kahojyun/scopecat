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
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_analysis,
    readout_frequency_template,
)
from scopecat.records.run import (
    AnalysisCandidateRunConfigSource,
    ConfigRegistryRunConfigSource,
)


def test_cli_project_serves_gui_and_lightweight_config_loop(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    """Exercise run, candidate, accept, history, and undo through one daemon."""

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
        assert "Set as default" in bundle
        assert "Undo" in bundle
        assert "/api/v1/config-registry" in bundle

        with sc.open_project(project).connect(daemon_url) as lab:
            baseline = lab.prepare(readout_frequency_template(qubit="q0")).run(
                name="first-use smoke",
                tags=("first-use",),
            )
            analysis = baseline.analyze(readout_frequency_analysis(qubit="q0"))
            saved = analysis.save()
            candidate = analysis.candidate_config()
            candidate_run = lab.prepare(
                readout_frequency_template(qubit="q0"),
                config=candidate,
            ).run(
                name="first-use candidate",
                tags=("first-use", "candidate"),
            )
            accepted = lab.config.accept(
                candidate,
                note="accept the first-use fit",
            )
            default_run = lab.prepare(readout_frequency_template(qubit="q0")).run(
                name="first-use accepted default",
                tags=("first-use", "default"),
            )
            restored = lab.config.undo(note="restore the first-use default")

        with sc.connect(daemon_url) as observer:
            detail = observer.get_run(baseline.id)
            candidate_detail = observer.get_run(candidate_run.id)
            default_detail = observer.get_run(default_run.id)
            proposals = observer.parameter_proposals(baseline.id)
            registry = observer.config_registry()

        assert detail.manifest.status == "completed"
        assert detail.control.admission.request is not None
        assert detail.control.admission.request.metadata["name"] == "first-use smoke"
        assert detail.control.admission.request.metadata["tags"] == ["first-use"]
        assert saved.record.id == candidate.analysis_record_ids[0]
        candidate_source = candidate_detail.manifest.config_source
        assert isinstance(candidate_source, AnalysisCandidateRunConfigSource)
        assert candidate_source.source_run_id == baseline.id
        assert candidate_source.analysis_record_ids == candidate.analysis_record_ids
        assert candidate_source.proposal_ids == candidate.proposal_ids
        default_source = default_detail.manifest.config_source
        assert isinstance(default_source, ConfigRegistryRunConfigSource)
        assert default_source.entry_id == accepted.entry.id
        assert proposals.items[0].decisions[-1].decision == "approved"
        assert proposals.items[0].decisions[-1].authority.kind == "human"
        assert registry.active_state is not None
        assert registry.active_state == restored.active_state
        assert registry.active_state.active_entry_id != accepted.entry.id
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
