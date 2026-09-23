"""
env_validation.py
-----------------
Resolves and validates the Gamry-provided 32-bit Python environment a run
must happen under: interpreter path, Framework folder, PYTHONPATH/PATH, and
an import probe for potentiostat/pyproc_bridge/toolkitpy.

``pyproc_bridge`` never needs installing into that interpreter: it's pure
stdlib, so ``add_bridge_to_pythonpath`` just puts this process's own
``pyproc_bridge`` install on the child's ``PYTHONPATH`` instead. ``potentiostat``
does need to be resolvable there -- either a plain, non-editable ``pip
install`` (no PEP 660 editable install needed), or, for local development,
``source_root`` (e.g. a ``GAMRY_SOURCE_ROOT`` env var) pointing at a source
checkout, prepended to the child's ``PYTHONPATH`` instead. Leave it unset
once the real install is in place.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pyproc_bridge import add_bridge_to_pythonpath


def validate_gamry_python(gamry_python: str | None) -> str:
    """Validate that the given Gamry Python path is set, exists, and is executable."""
    if not gamry_python:
        raise RuntimeError("No Gamry Python interpreter path was given.")

    if not os.path.isfile(gamry_python):
        raise FileNotFoundError(f"Gamry Python does not exist or is not a file: {gamry_python!r}")

    if not os.access(gamry_python, os.X_OK):
        raise PermissionError(f"Gamry Python is not executable: {gamry_python!r}")

    return gamry_python


def resolve_framework_path(framework_path: str | None, gamry_python: str) -> str | None:
    """Use the explicitly given Framework path, else auto-detect it by walking
    up from the Gamry Python (``.../Gamry Instruments/Framework``). Returns
    ``None`` only if neither is found -- fine if ToolkitPy is instead installed
    into the interpreter's own site-packages."""
    if framework_path:
        if not os.path.isdir(framework_path):
            raise FileNotFoundError(f"Framework path is set to {framework_path!r}, but it is not a valid directory.")
        return framework_path

    for parent in Path(gamry_python).resolve().parents:
        candidate = parent / "Framework"
        if (candidate / "toolkitpy").is_dir():
            return str(candidate)
    return None


def build_subprocess_env(
    framework_path: str | None = None,
    source_root: str | None = None,
) -> dict[str, str]:
    """Copy os.environ and set PYTHONPATH to, when given, ``source_root``
    (dev-mode override -- see module docstring) plus, when known, the
    Framework path (so `import toolkitpy` resolves -- ToolkitPy ships there,
    not in site-packages) -- this process's own PYTHONPATH, if any, is
    replaced rather than inherited, so a 64-bit entry can't shadow the Gamry
    Python's own packages with an incompatible build. Framework also goes on
    PATH along with its pywin32_system32 folder (its bundled DLLs). Always
    also puts this process's own ``pyproc_bridge`` install on PYTHONPATH --
    see the module docstring."""
    env = os.environ.copy()

    pythonpath_parts = []
    if source_root:
        pythonpath_parts.append(str(source_root))
    if framework_path:
        pythonpath_parts.append(framework_path)
    if pythonpath_parts:
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    else:
        env.pop("PYTHONPATH", None)

    if framework_path:
        path_parts = [framework_path, os.path.join(framework_path, "pywin32_system32")]
        if env.get("PATH"):
            path_parts.append(env["PATH"])
        env["PATH"] = os.pathsep.join(path_parts)

    return add_bridge_to_pythonpath(env)


def _verify_import(gamry_python: str, env: dict[str, str], module: str, hint: str) -> None:
    """Probe the target interpreter to confirm ``import <module>`` resolves."""
    result = subprocess.run([gamry_python, "-c", f"import {module}"], env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise ImportError(
            f"Interpreter {gamry_python!r} cannot import {module}.\n"
            f"{hint}\n"
            f"PYTHONPATH: {env.get('PYTHONPATH')}\n"
            f"PATH: {env.get('PATH')}\n"
            f"Interpreter output:\n{(result.stderr or result.stdout).strip()}"
        )


def validate_and_prepare_environment(
    gamry_python: str | None,
    framework_path: str | None = None,
    source_root: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Run all validation steps and return the executable path and prepared environment."""
    gamry_python = validate_gamry_python(gamry_python)
    framework_path = resolve_framework_path(framework_path, gamry_python)
    env = build_subprocess_env(framework_path=framework_path, source_root=source_root)

    _verify_import(
        gamry_python,
        env,
        "potentiostat",
        "Either `pip install potentiostat` into this interpreter, or set "
        "GAMRY_SOURCE_ROOT to a checkout containing it.",
    )
    _verify_import(
        gamry_python,
        env,
        "pyproc_bridge",
        "add_bridge_to_pythonpath should have put this process's own "
        "pyproc_bridge install on the child's PYTHONPATH -- check that "
        "install is actually present (e.g. `uv sync`).",
    )
    _verify_import(
        gamry_python,
        env,
        "toolkitpy",
        "Follow Gamry's ToolkitPy install instructions for this interpreter, "
        "or set TOOLKITPY_HOME to the Framework folder.",
    )

    return gamry_python, env
