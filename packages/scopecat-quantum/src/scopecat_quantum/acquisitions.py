"""Hardware-independent acquisition result contracts."""

from enum import StrEnum


class AcquisitionKind(StrEnum):
    """The hardware-independent shape promised by an acquisition slot."""

    INTEGRATED_IQ = "integrated_iq"
    RAW_TRACE = "raw_trace"
