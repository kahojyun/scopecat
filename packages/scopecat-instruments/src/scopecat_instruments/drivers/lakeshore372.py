"""Safe read-only Lake Shore Model 372 sensor driver."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import override

from pydantic import JsonValue
from scopecat.records.measurement import (
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
)
from scopecat.sdk.instruments import (
    DriverOutcome,
    DriverSuccess,
    InstrumentDescription,
)
from scopecat.sdk.instruments.scpi import (
    ScpiIdentity,
    ScpiTransport,
    parse_bool,
    parse_int,
    query_float,
    query_identity,
    query_int,
    query_text,
)

from scopecat_instruments._support import collect_unknown
from scopecat_instruments.driver_handlers import (
    TemperatureReadoutDriverAdapter,
    TemperatureReadoutDriverSnapshot,
    TemperatureReadoutSampleDriverReadback,
    TemperatureReadoutSampleDriverResultName,
    TemperatureReadoutSampleDriverValues,
)
from scopecat_instruments.interface_declarations import TemperatureReadoutObservation
from scopecat_instruments.interfaces import temperature_readout_interface
from scopecat_instruments.package_manifest import LAKESHORE_372_DRIVER

_SETTLE_TIMEOUT_SECONDS = 10.0
_SETTLE_POLL_SECONDS = 0.05
_OVERLOAD_STATUS_BITS = 0x0F


@dataclass(frozen=True)
class _LakeShore372Sample:
    scan_channel: int
    autoscan_enabled: bool
    values: TemperatureReadoutSampleDriverValues
    curve_number: int | None


class LakeShore372(TemperatureReadoutDriverAdapter):
    """Observe scanner state and collect settled K/Ω samples without writes."""

    implementation_id = LAKESHORE_372_DRIVER.id
    implementation_version = LAKESHORE_372_DRIVER.implementation_version

    def __init__(self, instrument_id: str, transport: ScpiTransport) -> None:
        self.instrument_id = instrument_id
        self.transport = transport
        self._identity: ScpiIdentity | None = None

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Lake Shore 372",
            description=(
                "Safety-first read-only sensor driver. Heater, input, curve, and "
                "scanner configuration writes are intentionally unsupported."
            ),
            interfaces=[temperature_readout_interface()],
        )

    @override
    def read_temperature_readout_state(self) -> TemperatureReadoutDriverSnapshot:
        scan_channel, autoscan_enabled = self._scan_state()
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Lake Shore Cryotronics",
            "model": "372",
            "control_boundary": "read_only",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return TemperatureReadoutDriverSnapshot(
            observation=TemperatureReadoutObservation(
                scan_channel=scan_channel,
                autoscan_enabled=autoscan_enabled,
            ),
            metadata=metadata,
        )

    @override
    def handle_sample(
        self,
        requested: frozenset[TemperatureReadoutSampleDriverResultName],
        /,
    ) -> DriverOutcome[TemperatureReadoutSampleDriverReadback]:
        try:
            sample = self._read_sample(requested)
            metadata: dict[str, JsonValue] = {
                "manufacturer": "Lake Shore Cryotronics",
                "model": "372",
                "scan_channel": sample.scan_channel,
                "autoscan_enabled": sample.autoscan_enabled,
                "reading_status": 0,
            }
            if sample.curve_number is not None:
                metadata["curve_number"] = sample.curve_number
            return DriverSuccess(
                TemperatureReadoutSampleDriverReadback(
                    values=sample.values,
                    metadata=metadata,
                ),
            )
        except _SampleQualityUnavailable as error:
            quality_metadata: dict[str, JsonValue] = {
                "code": error.code,
                **error.details,
            }
            unavailable_values: TemperatureReadoutSampleDriverValues = {}
            if "temperature" in requested:
                unavailable_values["temperature"] = _unavailable_result(
                    "temperature",
                    reason=error.reason,
                    metadata=quality_metadata,
                )
            if "resistance" in requested:
                unavailable_values["resistance"] = _unavailable_result(
                    "resistance",
                    reason=error.reason,
                    metadata=quality_metadata,
                )
            return DriverSuccess(
                TemperatureReadoutSampleDriverReadback(
                    values=unavailable_values,
                    metadata={
                        "manufacturer": "Lake Shore Cryotronics",
                        "model": "372",
                        "quality_code": error.code,
                        **error.details,
                    },
                ),
            )
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def _read_sample(
        self,
        requested_results: frozenset[TemperatureReadoutSampleDriverResultName],
    ) -> _LakeShore372Sample:
        deadline = monotonic() + _SETTLE_TIMEOUT_SECONDS
        while True:
            initial_scan = self._scan_state()
            self._wait_for_settled_reading(deadline)
            settled_scan = self._scan_state()
            if settled_scan != initial_scan:
                self._pause_before_scan_retry(deadline)
                continue

            channel = settled_scan[0]
            curve_number: int | None = None
            values: TemperatureReadoutSampleDriverValues = {}
            if "temperature" in requested_results:
                curve_number = query_int(self.transport, f"INCRV? {channel}")
                if curve_number == 0:
                    values["temperature"] = _unavailable_result(
                        "temperature",
                        reason="missing",
                        metadata={
                            "code": "lakeshore_temperature_curve_missing",
                            "scan_channel": channel,
                            "curve_number": curve_number,
                        },
                    )
                else:
                    values["temperature"] = MeasurementScalar.create(
                        dtype="float64",
                        unit="K",
                        value=query_float(self.transport, f"KRDG? {channel}"),
                    )
            if "resistance" in requested_results:
                values["resistance"] = MeasurementScalar.create(
                    dtype="float64",
                    unit="Ohm",
                    value=query_float(self.transport, f"SRDG? {channel}"),
                )

            reading_status = query_int(self.transport, f"RDGST? {channel}")
            final_settle_status = self._active_settle_status()
            final_scan = self._scan_state()
            if final_scan != settled_scan or final_settle_status != 0:
                self._pause_before_scan_retry(deadline)
                continue
            if reading_status != 0:
                raise _SampleQualityUnavailable(
                    "lakeshore_reading_invalid",
                    f"Lake Shore 372 channel {channel} reported invalid reading "
                    f"status {reading_status}",
                    reason=_reading_status_reason(reading_status),
                    details={
                        "scan_channel": channel,
                        "reading_status": reading_status,
                    },
                )
            return _LakeShore372Sample(
                scan_channel=channel,
                autoscan_enabled=settled_scan[1],
                values=values,
                curve_number=curve_number,
            )

    def _scan_state(self) -> tuple[int, bool]:
        scan_response = query_text(self.transport, "SCAN?").split(",")
        if len(scan_response) != 2:
            raise ValueError("Lake Shore 372 returned malformed SCAN response")
        return (
            parse_int(scan_response[0], command="SCAN?"),
            parse_bool(scan_response[1], command="SCAN?"),
        )

    def _wait_for_settled_reading(self, deadline: float) -> None:
        while self._active_settle_status() != 0:
            if monotonic() >= deadline:
                raise _SampleQualityUnavailable(
                    "lakeshore_reading_settle_timeout",
                    "Lake Shore 372 active scan channel did not settle",
                    reason="invalid",
                )
            sleep(_SETTLE_POLL_SECONDS)

    def _active_settle_status(self) -> int:
        response = query_text(self.transport, "RDGSTL?").split(",")
        if len(response) != 2:
            raise ValueError("Lake Shore 372 returned malformed RDGSTL response")
        return parse_int(response[1], command="RDGSTL?")

    def _pause_before_scan_retry(self, deadline: float) -> None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise _SampleQualityUnavailable(
                "lakeshore_scan_coherence_timeout",
                "Lake Shore 372 scanner changed before a coherent sample was read",
                reason="invalid",
            )
        sleep(min(_SETTLE_POLL_SECONDS, remaining))

    def identify(self) -> ScpiIdentity:
        identity = query_identity(self.transport)
        manufacturer = identity.manufacturer.upper().replace(" ", "")
        model = identity.model.upper().replace(" ", "")
        if not (
            ("LSCI" in manufacturer or "LAKESHORE" in manufacturer)
            and model in {"MODEL372", "372"}
        ):
            raise ValueError(f"expected a Lake Shore 372, got {identity.raw!r}")
        self._identity = identity
        return identity

    def disconnect(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """Read-only sampling has no hardware operation to abort."""


class _SampleQualityUnavailable(Exception):
    code: str
    reason: MeasurementUnavailableReason
    details: dict[str, JsonValue]

    def __init__(
        self,
        code: str,
        message: str,
        *,
        reason: MeasurementUnavailableReason,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self.code = code
        self.reason = reason
        self.details = {} if details is None else details
        super().__init__(message)


def _unavailable_result(
    target: TemperatureReadoutSampleDriverResultName,
    *,
    reason: MeasurementUnavailableReason,
    metadata: dict[str, JsonValue],
) -> MeasurementUnavailable:
    units: dict[TemperatureReadoutSampleDriverResultName, str] = {
        "temperature": "K",
        "resistance": "Ohm",
    }
    return MeasurementUnavailable.create(
        reason=reason,
        dtype="float64",
        unit=units[target],
        shape=(),
        metadata=metadata,
    )


def _reading_status_reason(status: int) -> MeasurementUnavailableReason:
    """The manual labels only RDGST bits 0-3 as overloads."""

    return "overload" if status & _OVERLOAD_STATUS_BITS else "invalid"


__all__ = ["LakeShore372"]
