from scopecat.records.run import RunStageLineage
from scopecat.records.run_request import RunRequest
from scopecat.runs.admission import build_run_admission
from tests.testkit.workflow_fixtures import load_config


def test_run_admission_copies_typed_stage_lineage_to_manifest() -> None:
    lineage = RunStageLineage(
        sequence_id="adaptive-sequence",
        index=1,
        previous_run_id="run-first",
    )

    skeleton = build_run_admission(
        config=load_config(),
        request=RunRequest(stage=lineage),
    )

    assert skeleton.request.stage == lineage
    assert skeleton.manifest.stage == lineage
