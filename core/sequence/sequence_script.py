"""Worker side of the sequence runner.

Runs under the Gamry 32-bit interpreter. Connects back to the Supervisor,
waits for a TASK message carrying the ExecuteSequenceConfig, then runs the
sequence on a background thread so the socket stays responsive to ABORT.
Sends exactly one terminal message (RESULT / ERROR / ABORTED) and closes.
"""

import os
import threading

from potentiostat.core.sequence.sequence import execute_sequence_sync, ExecuteSequenceConfig
from potentiostat.core.workflow.emitter import dump_workflow_event
from pyproc_bridge import protocol
from pyproc_bridge.roles import Worker
from pyproc_bridge import AbortSignal, AbortError

port = int(os.getenv("GAMRY_IPC_PORT", "5050"))

worker = Worker()
abort = AbortSignal()


@worker.on(protocol.ABORT)
def _on_abort(_data):
    print("[Worker] abort requested")
    abort.abort("supervisor requested abort")


@worker.on(protocol.TASK)
def _on_task(data):
    threading.Thread(target=_run_sequence, args=(data,), daemon=True).start()


def _run_sequence(data):
    try:
        cfg = ExecuteSequenceConfig.model_validate(data)
        results = execute_sequence_sync(
            cfg,
            on_event=lambda event: worker.emit(protocol.EVENT, dump_workflow_event(event)),
            abort=abort,
        )
    except AbortError:
        worker.emit(protocol.ABORTED, True)
    except Exception as exc:  # noqa: BLE001 -- reported to the supervisor, then re-raised context is lost by design
        worker.emit(protocol.ERROR, {"error": repr(exc)})
    else:
        worker.emit(protocol.RESULT, results.model_dump_json())
    finally:
        worker.flush()  # make sure the terminal message is on the wire
        worker.close()


if __name__ == "__main__":
    worker.connect(port=port)
    try:
        worker.wait()
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()
