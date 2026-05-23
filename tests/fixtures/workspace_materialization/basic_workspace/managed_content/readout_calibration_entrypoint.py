"""Public-safe materialized entrypoint fixture."""

RUN_LABEL = "readout-rerun-0001"


def build_sequence():
    return ["prepare_readout", "measure_iq", "save_summary"]
