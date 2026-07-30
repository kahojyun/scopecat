from __future__ import annotations

from typing import assert_type

import scopecat as sc

from scopecat_instruments import (
    DCSourceTarget,
    DCSourceVoltageTarget,
    NetworkSweepTarget,
)
from scopecat_instruments.members import (
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
)


def test_voltage_target_accepts_fixed_and_scanned_desired_values() -> None:
    level = sc.coordinate(
        "dc_bias",
        sc.ScalarType(sc.QuantityType(unit="V")),
    )
    target = DCSourceVoltageTarget(
        range=sc.Quantity(1.0, "V"),
        level=level,
        output_enabled=True,
    )

    assert_type(target, DCSourceVoltageTarget)
    assert target.target_assignments() == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_RANGE: sc.Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: level,
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_targets_omit_unspecified_properties() -> None:
    assert DCSourceTarget(output_enabled=False).target_assignments() == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert NetworkSweepTarget(
        start_frequency=sc.Quantity(4.8, "GHz"),
        points=401,
        s_parameter="S21",
    ).target_assignments() == {
        NETWORK_SWEEP_START_FREQUENCY: sc.Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }
