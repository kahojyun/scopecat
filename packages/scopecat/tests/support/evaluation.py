from __future__ import annotations

from pathlib import Path

from scopecat.evaluation import EvaluationJob
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.run import RunManifest
from scopecat.runs import open_run_store
from tests.support.records import assert_artifact_ref, read_model
from tests.support.signal_testkit import execute_signal_native_run

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def simulate(tmp_path: Path) -> str:
    manifest, _simulated_run = execute_signal_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


def assert_failed_evaluation_job(
    tmp_path: Path,
    run_id: str,
    *,
    step_id: str,
    diagnostic_code: str,
) -> tuple[EvaluationJob, RunManifest]:
    job_ref = f"evaluation/{step_id}.job.json"
    job_path = tmp_path / "runs" / run_id / job_ref
    assert job_path.is_file()
    job = read_model(job_path, EvaluationJob)
    assert job.id == step_id
    assert job.step == step_id
    assert job.status == "failed"
    assert [diagnostic.code for diagnostic in job.diagnostics] == [diagnostic_code]
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        f"{step_id}-job",
        kind="evaluation_job",
        path=job_ref,
    )
    return job, manifest
