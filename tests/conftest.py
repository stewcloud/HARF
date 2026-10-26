"""Load pure core without importing Home Assistant adapters."""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "rf_core", Path(__file__).parents[1] / "custom_components/harf/core.py"
)
core = importlib.util.module_from_spec(spec)
sys.modules["rf_core"] = core
spec.loader.exec_module(core)
