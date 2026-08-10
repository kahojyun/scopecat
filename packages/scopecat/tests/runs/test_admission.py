from scopecat.records.run import RunSequenceLineage
from scopecat.records.run_request import RunRequest
from scopecat.runs.admission import build_run_admission
from tests.testkit.workflow_fixtures import load_config


def test_run_admission_copies_typed_stage_lineage_to_manifest() -> None:
    lineage = RunSequenceLineage(
        sequence_id="adaptive-sequence",
        run_index=1,
        previous_run_id="run-first",
    )

    skeleton = build_run_admission(
        config=load_config(),
        request=RunRequest(sequence=lineage),
    )

    assert skeleton.request.sequence == lineage
    assert skeleton.manifest.sequence == lineage
