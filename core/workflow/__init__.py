"""Run-lifecycle plumbing for the sequence driver: the event emitter and its
events (``emitter``). The cooperative abort signal and side-thread ``Future``
helpers (``AbortSignal``/``submit``/``map_future``) live in the external
``pyproc-bridge`` package instead."""
