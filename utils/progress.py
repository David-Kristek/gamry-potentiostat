"""
progress.py
------------
Shared progress/timing logger for the long-running technique loops
(OCP/EIS/LPR/CPP).
"""

from __future__ import annotations

import logging
import time
from functools import wraps


def configure_logging(level: int = logging.INFO) -> None:
    """Call once from main.py before running any technique: timestamps every
    log line so progress output can be read like a timeline."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes:d}m{secs:02d}s"
    return f"{secs:d}s"


def throttle(seconds: float):
    def decorator(func):
        last_called = 0.0

        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_called
            now = time.monotonic()
            if now - last_called >= seconds:
                last_called = now
                return func(*args, **kwargs)
            return None

        return wrapper

    return decorator


def estimate_technique_duration(name: str, cfg) -> float | None:
    if name == "ocp":
        return cfg.total_time_s
    if name == "lpr":
        return abs(cfg.v_final_v - cfg.v_init_v) / abs(cfg.scan_rate_v_s)
    if name == "cpp":
        fwd = abs(cfg.v_apex_v - cfg.v_init_v) / abs(cfg.scan_fwd_v_s)
        rev = abs(cfg.v_final_v - cfg.v_apex_v) / abs(cfg.scan_rev_v_s)
        return fwd + rev
    return None


def fraction_eta(elapsed_s: float, expected_s: float | None) -> tuple[float | None, float | None]:
    """Linear fraction-done/ETA from elapsed time and an expected total
    duration (see `estimate_technique_duration`) -- both None if no expected
    duration is known; eta_s stays None until fraction crosses 1% (too noisy
    to estimate before then)."""
    if not expected_s:
        return None, None
    fraction = max(0.0, min(1.0, elapsed_s / expected_s))
    if fraction < 0.01:
        return fraction, None
    return fraction, elapsed_s / fraction * (1 - fraction)


class ProgressReporter:
    """Throttled elapsed/remaining-time logger for one technique's run loop.
    Time is estimated only lineary, from `expected_duration_s` (see
    `estimate_technique_duration`) if given -- otherwise only elapsed time
    is logged, with no percent/ETA.
    """

    def __init__(
        self,
        logger: logging.Logger,
        label: str,
        min_interval_s: float = 5.0,
        expected_duration_s: float | None = None,
    ):
        self._logger = logger
        self._label = label
        self._min_interval_s = min_interval_s
        self._expected_duration_s = expected_duration_s
        self._start = time.monotonic()
        self._last_log = self._start

    def update(self, extra: str = "", force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_log) < self._min_interval_s:
            return
        self._last_log = now

        elapsed = now - self._start

        fraction_done, remaining = fraction_eta(elapsed, self._expected_duration_s)
        percent = f"{fraction_done * 100:5.1f}% complete, " if fraction_done is not None else ""
        time_estimate = f", ~{format_duration(remaining)} remaining" if remaining else ""

        suffix = f" ({extra})" if extra else ""
        self._logger.info(f"[{self._label}] {percent}elapsed {format_duration(elapsed)}{time_estimate}{suffix}")

    def finish(self, extra: str = "") -> None:
        elapsed = time.monotonic() - self._start
        suffix = f" ({extra})" if extra else ""
        self._logger.info(f"[{self._label}] done in {format_duration(elapsed)}{suffix}")
