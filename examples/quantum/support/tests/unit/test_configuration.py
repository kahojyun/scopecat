from __future__ import annotations

from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.parameter import (
    ScalarParameterValue,
    TableParameterValue,
)

from quantum_lab_demo import quantum_lab_bootstrap_config


def test_bootstrap_config_combines_schema_files_with_python_parameter_tables() -> None:
    config = quantum_lab_bootstrap_config()

    assert (
        validate_parameter_snapshot(
            config.parameter_catalog,
            config.parameter_snapshot,
        )
        == ()
    )
    repetitions = config.parameter_snapshot.get("repetitions")
    qubits = config.parameter_snapshot.get("qubits")
    gates = config.parameter_snapshot.get("two_qubit_gates")
    assert repetitions == ScalarParameterValue(
        id="repetitions",
        value=Quantity(value=128.0, unit="count"),
    )
    assert isinstance(qubits, TableParameterValue)
    assert [row["qubit"] for row in qubits.rows] == [
        EntityRef(id=f"q{index}", kind="logical_qubit") for index in range(4)
    ]
    assert qubits.rows[3]["drive_frequency"] == Quantity(value=5.48, unit="GHz")
    assert isinstance(gates, TableParameterValue)
    assert [
        (
            row["control_qubit"],
            row["partner_qubit"],
            row["gate"],
        )
        for row in gates.rows
    ] == [
        (
            EntityRef(id="q0", kind="logical_qubit"),
            EntityRef(id="q1", kind="logical_qubit"),
            "cz",
        ),
        (
            EntityRef(id="q2", kind="logical_qubit"),
            EntityRef(id="q3", kind="logical_qubit"),
            "cz",
        ),
    ]
