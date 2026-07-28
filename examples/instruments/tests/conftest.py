"""Expose the example's source tree to its standalone test suite."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
source_path = str(SOURCE_ROOT)
if source_path not in sys.path:
    sys.path.insert(0, source_path)
