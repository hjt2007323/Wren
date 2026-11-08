"""Pytest plugin: run the suite against the *frozen upstream* formatter.

Purpose: prove the new budget tests are capable of failing (upstream Contribution
Bar: "every assertion must be capable of failing").  Loading this plugin swaps
``wren_langchain._format`` for the byte-frozen baseline before collection, so the
same test file runs red against the unfixed code.

    PYTHONPATH=tools python -m pytest sdk/wren-langchain/tests/unit/test_format_budget.py \
        -p pytest_upstream_format
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BASELINE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "evidence"
    / "baseline"
    / "upstream_format_548eee3e.py"
)


def pytest_configure(config):  # noqa: ARG001 - pytest hook signature
    if "wren_langchain._format" in sys.modules:
        raise RuntimeError("wren_langchain._format already imported; run this plugin first")
    spec = importlib.util.spec_from_file_location("wren_langchain._format", BASELINE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules["wren_langchain._format"] = module
