import concurrent.futures as futures
import os
from typing import Any, Callable

from potentiostat.gamry_potentiostat.env_validation import (
    resolve_source_root,
    validate_and_prepare_environment,
)
from potentiostat.core.workflow.emitter import WorkflowEvent, parse_workflow_event
from potentiostat.core.sequence.sequence import ExecuteSequenceConfig, SequenceResults
from pyproc_bridge import AbortSignal, map_future, submit
from pyproc_bridge.launcher import run_legacy_python_worker_sync


def run_gamry_python_script(
    module: str,
    task: dict[str, Any],
    on_event: Callable[[Any], None],
    parse_event: Callable[[Any], Any],
    abort: AbortSignal,
    port: int = 5050,
) -> futures.Future[str]:

    def _run() -> str:
        source_root = resolve_source_root()
        gamry_python, env = validate_and_prepare_environment(
            os.getenv("GAMRY_PYTHON"), os.getenv("TOOLKITPY_HOME"), source_root
        )
        return run_legacy_python_worker_sync(
            gamry_python,
            module,
            task,
            on_event,
            abort,
            port=port,
            env=env,
            port_env_var="GAMRY_IPC_PORT",
            cwd=source_root,
            worker_label="gamry worker",
            parse_event=parse_event,
        )

    return submit(_run, thread_name=f"gamry-worker[{module}]")


def run_sequence(
    sequence_config: ExecuteSequenceConfig,
    on_event: Callable[[WorkflowEvent], None],
    abort: AbortSignal,
) -> futures.Future[SequenceResults]:
    raw_future = run_gamry_python_script(
        "potentiostat.core.sequence.sequence_script",
        sequence_config.model_dump(mode="json"),
        on_event,
        parse_workflow_event,
        abort,
    )
    return map_future(raw_future, SequenceResults.model_validate_json)
