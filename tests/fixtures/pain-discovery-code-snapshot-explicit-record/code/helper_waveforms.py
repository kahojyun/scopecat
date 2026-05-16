"""Text-only public fixture helper.

This helper exists to test whether dependent code references need snapshot
capture before a broader code registry exists.
"""

raise RuntimeError("fixture code must not be executed")


def make_public_waveform(length):
    return [0.0] * length
