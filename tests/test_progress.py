"""Progress helpers: duration formatting, the throttle decorator, the
per-technique duration model, and the fraction/ETA math on top of it."""

from __future__ import annotations

import pytest

from potentiostat.parsing.sequence_config import CPPConfig, LPRConfig, OCPConfig
from potentiostat.utils import progress
from potentiostat.utils.progress import (
    estimate_technique_duration,
    format_duration,
    fraction_eta,
    throttle,
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.0, "0s"),
        (59.9, "59s"),
        (60.0, "1m00s"),
        (125.0, "2m05s"),
        (3600.0, "1h00m00s"),
        (3661.0, "1h01m01s"),
        (-5.0, "0s"),  # clamped, never negative
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


class _Clock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def test_throttle_drops_calls_inside_the_window(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(progress.time, "monotonic", clock)

    calls = []

    @throttle(0.5)
    def record(x):
        calls.append(x)
        return x

    assert record(1) == 1  # first call always passes

    clock.t += 0.2
    assert record(2) is None  # inside the window -> swallowed

    clock.t += 0.3  # 0.5s since the last *accepted* call
    assert record(3) == 3

    assert calls == [1, 3]


def test_estimate_technique_duration_per_technique():
    assert estimate_technique_duration("ocp", OCPConfig(total_time_s=12.5)) == 12.5
    assert estimate_technique_duration("lpr", LPRConfig(v_init_v=-0.01, v_final_v=0.01, scan_rate_v_s=0.001)) == 20.0
    assert (
        estimate_technique_duration(
            "cpp",
            CPPConfig(v_init_v=-0.25, v_apex_v=1.75, v_final_v=0.0, scan_fwd_v_s=0.001, scan_rev_v_s=0.002),
        )
        == 2000.0 + 875.0
    )
    assert estimate_technique_duration("eis", object()) is None


def test_fraction_eta_without_expected_duration():
    assert fraction_eta(10.0, None) == (None, None)
    assert fraction_eta(10.0, 0.0) == (None, None)


def test_fraction_eta_midway():
    fraction, eta = fraction_eta(elapsed_s=50.0, expected_s=100.0)
    assert fraction == 0.5
    assert eta == 50.0


def test_fraction_eta_below_one_percent_has_no_estimate_yet():
    fraction, eta = fraction_eta(elapsed_s=0.5, expected_s=100.0)
    assert fraction == 0.005
    assert eta is None


def test_fraction_eta_clamps_past_the_end():
    fraction, eta = fraction_eta(elapsed_s=250.0, expected_s=100.0)
    assert fraction == 1.0
    assert eta == 0.0
