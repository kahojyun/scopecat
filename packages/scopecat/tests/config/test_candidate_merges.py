from __future__ import annotations

from collections.abc import Mapping

import pytest
from scopecat_testkit.workflow_fixtures import load_config

from scopecat.config.candidate_merges import (
    merge_common_base_parameter_proposals,
)
from scopecat.kernel.errors import CheckFailed, Conflict
from scopecat.kernel.value_types import Float, Scalar, String, Table, TableColumn
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter import (
    ParameterAtomValue,
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    ScalarParameterValue,
    TableParameterValue,
)
from scopecat.records.parameter_change import (
    ParameterChangeProposal,
    ParameterValueDelta,
)


def test_common_base_keyed_table_merge_is_cell_aware_and_order_independent() -> None:
    base = _base_config()
    q0 = _proposal(
        base,
        run_id="procedure-q0",
        proposal_id="proposal-q0",
        after=_qubits(base, q0_beta=0.25),
    )
    q1 = _proposal(
        base,
        run_id="procedure-q1",
        proposal_id="proposal-q1",
        after=_qubits(base, q1_beta=-0.5),
    )

    forward = merge_common_base_parameter_proposals(
        (q0, q1),
        base_config=base,
        candidate_id="merged-drag",
    )
    reverse = merge_common_base_parameter_proposals(
        (q1, q0),
        base_config=base,
        candidate_id="merged-drag",
    )

    assert forward == reverse
    assert forward.content_hash == config_content_hash(reverse.config)
    assert tuple(delta.parameter_id for delta in forward.deltas) == ("qubits",)
    merged = forward.config.parameter_snapshot.get("qubits")
    assert isinstance(merged, TableParameterValue)
    assert tuple(row["qubit"] for row in merged.rows) == ("q0", "q1")
    assert merged.rows[0]["beta"] == 0.25
    assert merged.rows[1]["beta"] == -0.5


def test_common_base_merge_accepts_one_proposal_as_identity_composition() -> None:
    base = _base_config()
    proposal = _proposal(
        base,
        run_id="procedure-q0",
        proposal_id="proposal-q0",
        after=_qubits(base, q0_beta=0.25),
    )

    result = merge_common_base_parameter_proposals(
        (proposal,),
        base_config=base,
        candidate_id="single-drag",
    )

    assert result.deltas == proposal.deltas
    assert result.config.id == "single-drag"
    assert result.config.parameter_snapshot.id == "single-drag.parameters"
    assert result.config.parameter_snapshot.get("qubits") == proposal.deltas[0].after


def test_common_base_merge_still_rejects_an_empty_composition() -> None:
    with pytest.raises(CheckFailed) as error:
        merge_common_base_parameter_proposals(
            (),
            base_config=_base_config(),
            candidate_id="empty",
        )

    assert error.value.problems[0].code == "parameter_merge.proposal_count"


def test_common_base_keyed_table_merges_different_cells_in_one_row() -> None:
    base = _base_config()
    beta = _proposal(
        base,
        run_id="procedure-beta",
        proposal_id="proposal-beta",
        after=_qubits(base, q0_beta=0.25),
    )
    amplitude = _proposal(
        base,
        run_id="procedure-amplitude",
        proposal_id="proposal-amplitude",
        after=_qubits(base, q0_amplitude=0.75),
    )

    result = merge_common_base_parameter_proposals(
        (beta, amplitude),
        base_config=base,
        candidate_id="merged-cells",
    )

    merged = result.config.parameter_snapshot.get("qubits")
    assert isinstance(merged, TableParameterValue)
    assert dict(merged.rows[0]) == {
        "qubit": "q0",
        "beta": 0.25,
        "amplitude": 0.75,
    }


def test_common_base_keyed_table_coalesces_equal_edits() -> None:
    base = _base_config()
    first = _proposal(
        base,
        run_id="procedure-a",
        proposal_id="proposal-a",
        after=_qubits(base, q0_beta=0.25),
    )
    second = _proposal(
        base,
        run_id="procedure-b",
        proposal_id="proposal-b",
        after=_qubits(base, q0_beta=0.25),
    )

    result = merge_common_base_parameter_proposals(
        (second, first),
        base_config=base,
        candidate_id="coalesced",
    )

    merged = result.config.parameter_snapshot.get("qubits")
    assert isinstance(merged, TableParameterValue)
    assert merged.rows[0]["beta"] == 0.25


def test_common_base_keyed_table_applies_delete_and_sorts_new_rows() -> None:
    base = _base_config()
    qubits = _required_table(base, "qubits")
    delete_q0_insert_q3 = _proposal(
        base,
        run_id="procedure-q3",
        proposal_id="proposal-q3",
        after=qubits.model_copy(
            update={
                "rows": (
                    qubits.rows[1],
                    {"qubit": "q3", "beta": 0.3, "amplitude": 1.0},
                )
            }
        ),
    )
    insert_q2 = _proposal(
        base,
        run_id="procedure-q2",
        proposal_id="proposal-q2",
        after=qubits.model_copy(
            update={
                "rows": (
                    *qubits.rows,
                    {"qubit": "q2", "beta": 0.2, "amplitude": 1.0},
                )
            }
        ),
    )

    result = merge_common_base_parameter_proposals(
        (delete_q0_insert_q3, insert_q2),
        base_config=base,
        candidate_id="rows",
    )

    merged = result.config.parameter_snapshot.get("qubits")
    assert isinstance(merged, TableParameterValue)
    assert tuple(row["qubit"] for row in merged.rows) == ("q1", "q2", "q3")


@pytest.mark.parametrize(
    ("left", "right", "code"),
    [
        (
            ({"qubit": "q1", "beta": 0.0, "amplitude": 1.0},),
            (
                {"qubit": "q0", "beta": 0.2, "amplitude": 1.0},
                {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
            ),
            "parameter_merge.row_delete_edit_conflict",
        ),
        (
            (
                {"qubit": "q0", "beta": 0.2, "amplitude": 1.0},
                {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
            ),
            (
                {"qubit": "q0", "beta": 0.4, "amplitude": 1.0},
                {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
            ),
            "parameter_merge.table_cell_conflict",
        ),
        (
            (
                {"qubit": "q0", "beta": 0.0, "amplitude": 1.0},
                {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
                {"qubit": "q2", "beta": 0.2, "amplitude": 1.0},
            ),
            (
                {"qubit": "q0", "beta": 0.0, "amplitude": 1.0},
                {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
                {"qubit": "q2", "beta": 0.4, "amplitude": 1.0},
            ),
            "parameter_merge.row_insert_conflict",
        ),
    ],
)
def test_common_base_keyed_table_rejects_conflicting_row_operations(
    left: tuple[Mapping[str, ParameterAtomValue], ...],
    right: tuple[Mapping[str, ParameterAtomValue], ...],
    code: str,
) -> None:
    base = _base_config()
    proposals = (
        _proposal(
            base,
            run_id="procedure-left",
            proposal_id="proposal-left",
            after=TableParameterValue(id="qubits", rows=left),
        ),
        _proposal(
            base,
            run_id="procedure-right",
            proposal_id="proposal-right",
            after=TableParameterValue(id="qubits", rows=right),
        ),
    )

    with pytest.raises(Conflict) as error:
        merge_common_base_parameter_proposals(
            proposals,
            base_config=base,
            candidate_id="conflict",
        )

    assert error.value.problems[0].code == code


def test_common_base_merge_keeps_scalar_and_unkeyed_table_atomic() -> None:
    base = _base_config()
    scalar_a = _proposal(
        base,
        run_id="procedure-scalar-a",
        proposal_id="proposal-scalar-a",
        after=ScalarParameterValue(id="threshold", value=0.5),
    )
    scalar_b = _proposal(
        base,
        run_id="procedure-scalar-b",
        proposal_id="proposal-scalar-b",
        after=ScalarParameterValue(id="threshold", value=0.75),
    )

    with pytest.raises(Conflict) as scalar_error:
        merge_common_base_parameter_proposals(
            (scalar_a, scalar_b),
            base_config=base,
            candidate_id="scalar-conflict",
        )
    assert scalar_error.value.problems[0].code == (
        "parameter_merge.atomic_value_conflict"
    )

    unkeyed = _required_table(base, "scan_points")
    table_a = _proposal(
        base,
        run_id="procedure-table-a",
        proposal_id="proposal-table-a",
        after=unkeyed.model_copy(update={"rows": ({"value": 2.0},)}),
    )
    table_b = _proposal(
        base,
        run_id="procedure-table-b",
        proposal_id="proposal-table-b",
        after=unkeyed.model_copy(update={"rows": ({"value": 3.0},)}),
    )

    with pytest.raises(Conflict) as table_error:
        merge_common_base_parameter_proposals(
            (table_a, table_b),
            base_config=base,
            candidate_id="table-conflict",
        )
    assert table_error.value.problems[0].code == (
        "parameter_merge.atomic_table_conflict"
    )


def test_common_base_keyed_table_ignores_pure_row_reorder() -> None:
    base = _base_config()
    qubits = _required_table(base, "qubits")
    reorder = _proposal(
        base,
        run_id="procedure-reorder",
        proposal_id="proposal-reorder",
        after=qubits.model_copy(update={"rows": tuple(reversed(qubits.rows))}),
    )
    scalar = _proposal(
        base,
        run_id="procedure-scalar",
        proposal_id="proposal-scalar",
        after=ScalarParameterValue(id="threshold", value=0.5),
    )

    result = merge_common_base_parameter_proposals(
        (reorder, scalar),
        base_config=base,
        candidate_id="ignore-reorder",
    )

    assert tuple(delta.parameter_id for delta in result.deltas) == ("threshold",)
    assert result.config.parameter_snapshot.get("qubits") == qubits


def test_common_base_merge_rejects_a_stale_proposal_base() -> None:
    base = _base_config()
    after = _qubits(base, q0_beta=0.25)
    first = _proposal(
        base,
        run_id="procedure-current",
        proposal_id="proposal-current",
        after=after,
    )
    stale = _proposal(
        base,
        run_id="procedure-stale",
        proposal_id="proposal-stale",
        after=after,
    ).model_copy(update={"base_config_id": "different-base"})

    with pytest.raises(Conflict) as error:
        merge_common_base_parameter_proposals(
            (first, stale),
            base_config=base,
            candidate_id="stale",
        )

    assert error.value.problems[0].code == "parameter_merge.proposal_base_mismatch"


def test_common_base_merge_rejects_only_semantic_noops() -> None:
    base = _base_config()
    qubits = _required_table(base, "qubits")
    proposals = tuple(
        _proposal(
            base,
            run_id=f"procedure-{index}",
            proposal_id=f"proposal-{index}",
            after=qubits.model_copy(update={"rows": tuple(reversed(qubits.rows))}),
        )
        for index in range(2)
    )

    with pytest.raises(CheckFailed) as error:
        merge_common_base_parameter_proposals(
            proposals,
            base_config=base,
            candidate_id="noops",
        )

    assert error.value.problems[0].code == "parameter_merge.no_effective_changes"


def _base_config() -> ConfigProfileSnapshot:
    template = load_config()
    catalog = ParameterCatalog(
        id="merge-catalog",
        definitions=(
            ParameterDefinition(
                id="qubits",
                value_type=Table(
                    columns=(
                        TableColumn("qubit", Scalar(String())),
                        TableColumn("beta", Scalar(Float())),
                        TableColumn("amplitude", Scalar(Float())),
                    ),
                    primary_key=("qubit",),
                ),
            ),
            ParameterDefinition(id="threshold", value_type=Scalar(Float())),
            ParameterDefinition(
                id="scan_points",
                value_type=Table(
                    columns=(TableColumn("value", Scalar(Float())),),
                ),
            ),
        ),
    )
    snapshot = ParameterSnapshot(
        id="merge-base.parameters",
        values=(
            TableParameterValue(
                id="qubits",
                rows=(
                    {"qubit": "q0", "beta": 0.0, "amplitude": 1.0},
                    {"qubit": "q1", "beta": 0.0, "amplitude": 1.0},
                ),
            ),
            ScalarParameterValue(id="threshold", value=0.0),
            TableParameterValue(id="scan_points", rows=({"value": 1.0},)),
        ),
    )
    return template.model_copy(
        update={
            "id": "merge-base",
            "system": template.system.model_copy(
                update={"parameter_catalog": catalog},
                deep=True,
            ),
            "parameter_snapshot": snapshot,
        },
        deep=True,
    )


def _proposal(
    base: ConfigProfileSnapshot,
    *,
    run_id: str,
    proposal_id: str,
    after: ScalarParameterValue | TableParameterValue,
) -> ParameterChangeProposal:
    before = base.parameter_snapshot.get(after.id)
    assert before is not None
    return ParameterChangeProposal(
        id=proposal_id,
        source_run_id=run_id,
        analysis_record_id=f"analysis-{proposal_id}",
        base_config_id=base.id,
        base_config_content_hash=config_content_hash(base),
        reason="test merge contribution",
        deltas=(
            ParameterValueDelta(
                parameter_id=after.id,
                before=before,
                after=after,
            ),
        ),
    )


def _qubits(
    base: ConfigProfileSnapshot,
    *,
    q0_beta: float = 0.0,
    q1_beta: float = 0.0,
    q0_amplitude: float = 1.0,
) -> TableParameterValue:
    qubits = _required_table(base, "qubits")
    return qubits.model_copy(
        update={
            "rows": (
                {
                    "qubit": "q0",
                    "beta": q0_beta,
                    "amplitude": q0_amplitude,
                },
                {"qubit": "q1", "beta": q1_beta, "amplitude": 1.0},
            )
        }
    )


def _required_table(
    config: ConfigProfileSnapshot,
    parameter_id: str,
) -> TableParameterValue:
    value = config.parameter_snapshot.get(parameter_id)
    assert isinstance(value, TableParameterValue)
    return value
