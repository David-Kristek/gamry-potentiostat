"""Gamry-specific, host-side code: resolving/validating the Gamry 32-bit
Python environment (``env_validation.py``) and spawning it as an IPC worker
(``runner.py``, built on the external ``pyproc_bridge.launcher``). Runs on
whatever interpreter launches a measurement -- unlike ``core/``, nothing here
needs to run under the Gamry 32-bit interpreter itself.
"""
