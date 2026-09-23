"""Everything that must execute under the Gamry-provided 32-bit Python 3.7:
hardware I/O (``toolkitpy``), the technique runners, the sequence driver, and
its event/abort plumbing. ``toolkitpy`` is imported lazily inside the functions
that touch it, so these modules stay importable on any interpreter -- only
running them needs the Gamry Python. Keep this subpackage 3.7-compatible.

``sequence_script.py`` is the module actually invoked as
``python -m core.sequence_script`` under that interpreter -- it imports the
IPC transport directly (``pyproc_bridge.roles.Worker``), so that package
does need to be installed on the 32-bit side too (see
``gamry_potentiostat/env_validation.py``). The host-side Gamry launcher
(``gamry_potentiostat``) lives as a separate top-level package, not under
``core`` -- it's the one piece here that does *not* need to run under the
32-bit interpreter.
"""
