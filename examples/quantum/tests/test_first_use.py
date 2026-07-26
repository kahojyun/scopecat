from __future__ import annotations

from typing import Protocol

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


class _DemoDaemon(Protocol):
    url: str


def test_daemon_client_closes_config_provenance_loop(
    demo_daemon: _DemoDaemon,
) -> None:
    """Exercise run, candidate, accept, history, and undo through one daemon."""

    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as lab:
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

    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as observer:
        detail = observer.control.run_detail(baseline.id)
        request = observer.get_run(baseline.id).request
        candidate_detail = observer.control.run_detail(candidate_run.id)
        default_detail = observer.control.run_detail(default_run.id)
        proposals = observer.config.proposals(baseline.id)
        registry = observer.config.registry()

    assert detail.manifest.status == "completed"
    assert request.metadata["name"] == "first-use smoke"
    assert request.metadata["tags"] == ["first-use"]
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
