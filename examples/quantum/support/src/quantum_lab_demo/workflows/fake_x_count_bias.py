"""Mixed simple-instrument and list-program workflow."""

from __future__ import annotations

import scopecat as sc
from scopecat.kernel.state import StateLiteral
from scopecat.records.config import (
    ConfigProfileSnapshot,
    Device,
    InstrumentSpec,
    RoutingEndpointBinding,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    SimpleInstrumentDriver,
    SimpleProduct,
    SimpleStateField,
    product,
    quantity_field,
    simple_capability,
)

from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.fake_x_count_experiment import (
    DEFAULT_X_COUNTS,
    X_COUNT,
    fake_x_count_capture,
)

BIAS_SOURCE_ID = "bias-source"
BIAS_CAPABILITY_ID = "dc_voltage"
DEFAULT_BIAS_VOLTAGES = (-0.1, 0.1)

BIAS_VOLTAGE = sc.coordinate(
    "bias_voltage",
    sc.ScalarType(sc.QuantityType(unit="V")),
)


@sc.module(id="quantum_lab_demo.workflows.fake_x_count.bias_source")
def fake_bias_source():
    return (
        sc.module_body()
        .resource("bias", requires=(BIAS_CAPABILITY_ID,))
        .bind_field(
            "bias",
            capability=BIAS_CAPABILITY_ID,
            field="voltage",
            value=BIAS_VOLTAGE,
        )
        .product(
            "voltage_readback",
            unit="V",
        )
        .acquire(
            "read-voltage",
            "voltage_readback",
            resource="bias",
            capability=BIAS_CAPABILITY_ID,
            product_key="voltage",
        )
    )


@sc.template(
    id="quantum_lab_demo.workflows.fake_x_count.bias",
    kind="fake-x-count-bias",
    label="Fake AWG X-count scan with DC bias",
    description=(
        "Cross a point-local scalar voltage source with a programmable fake "
        "AWG list while retaining one logical measurement record per point."
    ),
)
def fake_x_count_bias_template() -> sc.ExperimentBody:
    capture = fake_x_count_capture(x_count=X_COUNT)
    bias_source = fake_bias_source()
    return (
        sc.experiment(capture, bias_source)
        .scan(
            sc.cartesian(
                sc.axis(BIAS_VOLTAGE, DEFAULT_BIAS_VOLTAGES, unit="V"),
                sc.axis(X_COUNT, DEFAULT_X_COUNTS),
            )
        )
        .record_product(
            capture.products.probability_0,
            capture.products.probability_1,
        )
        .record_product(
            bias_source.products.voltage_readback,
            record_id="bias_voltage_readback",
        )
    )


class FakeBiasVoltageProvider:
    """One scalar voltage source which cannot accept point lists or programs."""

    provider_id = "quantum_lab_demo.fake_bias_voltage_provider"

    def __init__(self) -> None:
        self._voltage = Quantity(value=0.0, unit="V")
        self._writes: list[Quantity] = []

    @property
    def voltage(self) -> Quantity:
        return self._voltage.model_copy(deep=True)

    @property
    def writes(self) -> tuple[Quantity, ...]:
        return tuple(value.model_copy(deep=True) for value in self._writes)

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(self._driver().describe(),),
            label="Fake scalar DC voltage source",
            description="Callback-backed point-local voltage source and readback.",
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        return InstrumentProviderResult(drivers=(self._driver(),))

    def _driver(self) -> SimpleInstrumentDriver:
        return SimpleInstrumentDriver(
            instrument_id=BIAS_SOURCE_ID,
            implementation_id="quantum_lab_demo.fake_bias_voltage_source",
            implementation_version="1",
            capabilities=(
                simple_capability(
                    BIAS_CAPABILITY_ID,
                    fields=(
                        SimpleStateField(
                            field=quantity_field("voltage", unit="V"),
                            read=lambda: self.voltage,
                            write=self._write_voltage,
                        ),
                    ),
                    products=(
                        SimpleProduct(
                            product=product("voltage", unit="V"),
                            read=lambda: self.voltage,
                        ),
                    ),
                    metadata={"submission_scope": "point"},
                ),
            ),
            metadata={"mode": "test_offline"},
        )

    def _write_voltage(self, value: StateLiteral) -> None:
        if not isinstance(value, Quantity):
            msg = "fake bias voltage source requires Quantity state"
            raise TypeError(msg)
        retained = value.model_copy(deep=True)
        self._voltage = retained
        self._writes.append(retained)


def fake_x_count_bias_config() -> ConfigProfileSnapshot:
    """Add the simple bias source to the standard demo quantum configuration."""

    config = quantum_wiring_config_profile()
    system = config.system
    return config.model_copy(
        update={
            "system": system.model_copy(
                update={
                    "topology": system.topology.model_copy(
                        update={
                            "devices": [
                                *system.topology.devices,
                                Device(id=BIAS_SOURCE_ID, kind="dc_voltage_source"),
                            ]
                        }
                    ),
                    "instrument_registry": system.instrument_registry.model_copy(
                        update={
                            "instruments": [
                                *system.instrument_registry.instruments,
                                InstrumentSpec(
                                    id=BIAS_SOURCE_ID,
                                    kind="dc_voltage_source",
                                ),
                            ]
                        }
                    ),
                    "routing": system.routing.model_copy(
                        update={
                            "bindings": [
                                *system.routing.bindings,
                                RoutingEndpointBinding(
                                    instrument_id=BIAS_SOURCE_ID,
                                    capability=BIAS_CAPABILITY_ID,
                                ),
                            ],
                        }
                    ),
                }
            )
        }
    )


__all__ = [
    "BIAS_CAPABILITY_ID",
    "BIAS_SOURCE_ID",
    "BIAS_VOLTAGE",
    "DEFAULT_BIAS_VOLTAGES",
    "FakeBiasVoltageProvider",
    "fake_bias_source",
    "fake_x_count_bias_config",
    "fake_x_count_bias_template",
]
