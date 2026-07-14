from scopecat.execution.effects.domain import DomainSynchronousCompletionPending


def test_synchronous_completion_pending_retains_target_job_context() -> None:
    error = DomainSynchronousCompletionPending(
        operation_id="domain:submission:fetch",
        job_id="target-job",
        submission_key="submission",
    )

    assert error.operation_id == "domain:submission:fetch"
    assert error.job_id == "target-job"
    assert error.submission_key == "submission"
    assert error.args == (
        "synchronous domain operation 'domain:submission:fetch' returned pending "
        "target job 'target-job'",
    )
    assert str(error) == error.args[0]
