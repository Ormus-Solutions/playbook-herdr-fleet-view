"""Shared paths for the tests. Every test runs offline on synthetic data."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEMO = ROOT / "examples" / "demo"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
