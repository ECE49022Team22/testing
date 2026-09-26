import os
import sys

import pytest

# Make the project root (cellular_test/) and this tests dir importable.
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
sys.path.insert(0, HERE)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: needs the real Notecard and/or network; run with RUN_HW=1"
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_HW") == "1":
        return
    skip_hw = pytest.mark.skip(reason="hardware/network test; set RUN_HW=1 to run")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hw)
