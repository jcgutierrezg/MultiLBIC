"""The import guard for the SMUniversal dependency.

MultiLBIC installs SMUniversal without its instrument libraries (see the
override list in pyproject.toml and docs/architecture.md). That rests on
two claims, and this file checks both:

1. the libraries really are absent, so the override is doing its job;
2. every SMUniversal module MultiLBIC uses still imports without them.

If a new SMUniversal pin starts needing one of the dropped packages,
this fails in CI when the pin moves, rather than on the Pi mid-scan.
"""

import importlib
import importlib.util

import pytest

# Import names, not distribution names (pyvisa-py imports as pyvisa_py).
DROPPED = [
    "pyvisa",
    "pyvisa_py",
    "usb",
    "libusb_package",
    "ni_gpib_usb_hs",
    "scipy",
]

# Every SMUniversal module MultiLBIC imports. Add to this list when a new
# one is used, before using it.
USED = [
    "smuniversal_lab_suite.drivers.undalogic_minismu",
    "smuniversal_lab_suite.core.transports.minismu_transport",
    "smuniversal_lab_suite.core.provenance",
    "smuniversal_lab_suite.core.event_log",
    "smuniversal_lab_suite.core.thread_guard",
    "smuniversal_lab_suite.core.single_instance",
    "smuniversal_lab_suite.core.gui.theme",
]


@pytest.mark.parametrize("name", DROPPED)
def test_dropped_library_is_not_installed(name):
    assert importlib.util.find_spec(name) is None, (
        f"{name} is installed: the override in pyproject.toml is not "
        "removing it"
    )


@pytest.mark.parametrize("name", USED)
def test_used_module_imports_without_dropped_libraries(name):
    importlib.import_module(name)


def test_minismu_library_has_streaming():
    from minismu_py import SMU

    for method in (
        "start_streaming",
        "stop_streaming",
        "read_streaming_data",
        "set_sample_rate",
    ):
        assert hasattr(SMU, method), method
