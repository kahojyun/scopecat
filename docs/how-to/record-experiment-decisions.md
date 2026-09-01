# Record a human or AI experiment decision

Use a procedure interpretation step when the next experiment action depends on
a scientific judgment that is not reliable enough to hard-code. Typical cases
include selecting real resonators from a broad S21 scan, mapping a resonator to
a qubit from a bias sweep, choosing a working point, or rejecting a fit whose
numeric diagnostics miss an obvious artifact.

Define the response as an ordinary stable analysis-fact schema. Keep measured
evidence in run or analysis records and put only presentation hints in request
metadata.

```python
from dataclasses import dataclass

from scopecat import AnalysisFactSchema
from scopecat.api.procedures import LabProcedureContext


@dataclass(frozen=True)
class ResonatorSelection:
    resonator: str
    center_frequency_hz: float
    confidence: float
    rationale: str


RESONATOR_SELECTION = AnalysisFactSchema(
    "my-lab.resonator-selection.v1",
    ResonatorSelection,
)


def continue_survey(
    context: LabProcedureContext,
    survey_run,
) -> None:
    decision = context.interpret(
        "select-resonator",
        title="Select a physical readout resonator",
        instructions=(
            "Inspect the broad S21 trace. Exclude cable ripple and duplicated "
            "fit candidates; return the selected physical resonator."
        ),
        schema=RESONATOR_SELECTION,
        inputs=(survey_run,),
        response_template=ResonatorSelection(
            resonator="replace after reviewing the trace",
            center_frequency_hz=0.0,
            confidence=0.0,
            rationale="replace with the experimental judgment",
        ),
        metadata={"preferred_view": "readout-s21"},
    )

    # This line runs only after an exact response has been recorded and the
    # procedure has been resumed. `decision.ref` carries durable provenance.
    selected = decision.value
    run_follow_up(
        context,
        resonator=selected.resonator,
        center_frequency_hz=selected.center_frequency_hz,
        inputs=(survey_run, decision.ref),
    )
```

The first execution stops in `waiting_for_input` and releases its worker lease.
Open **Decisions** in the project console, inspect the request and its named
evidence, identify the judging human, AI, or service, and record JSON matching
the displayed structure. An optional `response_template` is validated against
that structure and becomes the editor's starting value; use it to reduce
transcription without presenting it as an accepted decision. The recorded actor
is provenance supplied by the answering client, rather than an authenticated
account identity. The same operation is available from Python:

```python
procedure = lab.procedures.get(procedure_run_id)
procedure.respond(
    "select-resonator",
    ResonatorSelection(
        resonator="r2",
        center_frequency_hz=6.713e9,
        confidence=0.86,
        rationale="isolated dip with the expected bias response",
    ),
    schema=RESONATOR_SELECTION,
    actor="operator@example.org",
    actor_kind="human",  # also "ai" or "service"
    note="checked against the bias sweep",
)
```

Recording the response returns the procedure to `ready` but does not execute
the next experiment in that HTTP request. Without a resident project worker,
resume after checking that the next device action is appropriate:

```python
procedure.resume()
```

A configured resident project worker can claim the ready procedure on its next
poll. In that mode, recording the decision also authorizes the already-declared
continuation; pause the resident worker first when an additional manual hold is
required.

Use `attention_required` instead when a device or publication outcome is
unknown and must be reconciled. Do not turn an expected scientific choice into
an execution failure merely to pause the procedure.
