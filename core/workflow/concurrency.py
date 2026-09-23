"""Shared "run this on a side thread, hand back a Future" helper -- the
convention `execute_sequence` and the gamry_potentiostat runner both follow."""

from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def submit(fn: Callable[[], T], *, thread_name: str) -> Future[T]:
    """Run ``fn`` on a side thread, returning a ``Future`` for it immediately.

    ``.result(timeout=...)`` blocks and either returns the value or re-raises
    whatever ``fn`` raised; ``.done()`` polls without blocking;
    ``.add_done_callback(fn)`` still works if you want callback style.
    Nothing is printed or reported on its own -- if you never call
    ``.result()``/``.exception()``, a failure is silently discarded, same as
    any unread ``Future``.
    """
    fut: Future[T] = Future()

    def _run_in_background() -> None:
        try:
            fut.set_result(fn())
        except BaseException as exc:  # noqa: BLE001 -- carried by the future, not swallowed
            fut.set_exception(exc)

    threading.Thread(target=_run_in_background, daemon=True, name=thread_name).start()
    return fut


def map_future(future: Future[T], fn: Callable[[T], R]) -> Future[R]:
    """Return a new ``Future`` that resolves to ``fn(future.result())`` --
    chains a transform onto an existing future without spinning up another
    thread. Runs on whatever thread resolves ``future``. An exception from
    either ``future`` or ``fn`` is carried by the returned future, same as
    ``submit``."""
    mapped: Future[R] = Future()

    def _on_done(fut: Future[T]) -> None:
        if fut.cancelled():
            mapped.cancel()
            return
        exc = fut.exception()
        if exc is not None:
            mapped.set_exception(exc)
            return
        try:
            mapped.set_result(fn(fut.result()))
        except BaseException as e:  # noqa: BLE001 -- carried by the future, not swallowed
            mapped.set_exception(e)

    future.add_done_callback(_on_done)
    return mapped
