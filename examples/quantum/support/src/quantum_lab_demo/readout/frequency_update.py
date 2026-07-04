"""Readout-frequency parameter value update loop."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from pydantic import BaseModel, ConfigDict
from scopecat.config_registry import CandidateConfigRegistrySource
from scopecat.workflows import register_and_activate_candidate_config

from quantum_lab_demo.readout.analysis_steps import ReadoutFrequencyAnalysisStep

DEFAULT_NOTE = "private readout frequency calibration update"


class ReadoutFrequencyParameterUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    change_set_id: str
    candidate_record_id: str
    config_registry_entry_id: str
    active_entry_id: str


def execute_readout_frequency_parameter_update(
    *,
    run_id: str,
    workspace: str | Path,
    operator: str,
    entry_label: str | None = None,
    note: str = "",
) -> ReadoutFrequencyParameterUpdateResult:
    workspace_path = Path(workspace)
    lab = sc.open(workspace_path)
    return execute_readout_frequency_analysis_update(
        run=lab.get_run(run_id),
        workspace=workspace_path,
        operator=operator,
        entry_label=entry_label,
        note=note,
    )


def execute_readout_frequency_analysis_update(
    *,
    run: sc.Run,
    workspace: str | Path,
    operator: str,
    entry_label: str | None = None,
    note: str = "",
) -> ReadoutFrequencyParameterUpdateResult:
    workspace_path = Path(workspace)
    entry_id = entry_label or f"readout-frr-{run.id}"
    update_note = note or DEFAULT_NOTE

    analysis = run.analyze(ReadoutFrequencyAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    result = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=workspace_path,
        entry_id=entry_id,
        registered_by=operator,
        operator=operator,
        note=update_note,
    )
    source = result.entry.source
    if not isinstance(source, CandidateConfigRegistrySource):
        raise AssertionError("candidate activation did not record candidate record")

    return ReadoutFrequencyParameterUpdateResult(
        run_id=run.id,
        change_set_id=source.change_set_ids[0],
        candidate_record_id=source.candidate_record_id,
        config_registry_entry_id=result.entry.id,
        active_entry_id=result.active_state.active_entry_id,
    )
