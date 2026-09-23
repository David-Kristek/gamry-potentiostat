"""
abort.py
--------
Cooperative cancellation token for a running measurement sequence, modelled
on the DOM AbortSignal: an `aborted` flag, an optional `reason`, and abort
listeners fired once when it trips. Wiring up what calls `abort()` is the
caller's job.
"""

from __future__ import annotations

from typing import Any, Callable

AbortListener = Callable[[Any], None]


class AbortError(Exception):
    """Raised by AbortSignal.raise_if_aborted() once the signal has tripped."""


class AbortSignal:
    def __init__(self) -> None:
        self._aborted = False
        self._reason: Any = None
        self._listeners: list[AbortListener] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def __bool__(self) -> bool:
        return self._aborted

    def abort(self, reason: Any = None) -> None:
        """Trip the signal and fire every registered listener once. Repeat
        calls are no-ops."""
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason
        listeners, self._listeners = self._listeners, []
        for listener in listeners:
            listener(reason)

    def add_listener(self, listener: AbortListener) -> None:
        """Call `listener(reason)` when the signal trips -- immediately if it
        already has."""
        if self._aborted:
            listener(self._reason)
        else:
            self._listeners.append(listener)

    def remove_listener(self, listener: AbortListener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def raise_if_aborted(self) -> None:
        if self._aborted:
            raise AbortError(self._reason)
