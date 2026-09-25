"""Shared fixtures for the hardware-independent suite.

Everything here runs on the host interpreter with no Gamry Python and no
ToolkitPy: the tests cover only the pure logic that sits either side of the
hardware seam. Hardware handles are replaced by :class:`FakePstat`, a
duck-typed stand-in exposing just the surface that logic reads.
"""

from __future__ import annotations

import pytest


class FakePstat:
    """Duck-typed stand-in for a live ToolkitPy ``Pstat`` handle.

    Implements the attributes :mod:`potentiostat.core.hardware.device_validator`
    probes (``label`` / ``serial_no`` / ``model_no`` and the ``freq_limit_*``
    methods) plus ``has()`` for
    :func:`potentiostat.core.hardware.device.check_scan_resolution`.
    """

    def __init__(
        self,
        label: str = "Reference 600+",
        serial_no: str = "123456",
        model_no: str = "REFERENCE 600+",
        freq_min_hz: float = 10e-6,
        freq_max_hz: float = 5e6,
        has_ucb: bool = False,
    ):
        self._label = label
        self._serial_no = serial_no
        self._model_no = model_no
        self._freq_min_hz = freq_min_hz
        self._freq_max_hz = freq_max_hz
        self._has_ucb = has_ucb

    @property
    def label(self):
        return self._label

    @property
    def serial_no(self):
        return self._serial_no

    @property
    def model_no(self):
        return self._model_no

    def freq_limit_lower(self):
        return self._freq_min_hz

    def freq_limit_upper(self):
        return self._freq_max_hz

    def has(self, key):
        return key == "UCB" and self._has_ucb


@pytest.fixture
def make_fake_pstat():
    """Factory so each test can shape the fake handle it needs."""

    def _make(**kwargs):
        return FakePstat(**kwargs)

    return _make
