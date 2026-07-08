"""Headless plotting setup for Scopecat quantum readout reports."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "scopecat-matplotlib"),
)

import matplotlib

matplotlib.use("Agg", force=True)

from matplotlib import pyplot as plt

__all__ = ["plt"]
