"""Detached processes: job workers, compute sessions and the demo-data generator each run in a process of their own, so
they never block, or die with, the web server (and its reloads)."""

import os
import signal
import subprocess
from pathlib import Path

from api.config import APP_DIR


def spawn_detached(command: list[str], log_path: Path) -> int:
    """Start a process that outlives the API (and its reloads), its output appended to log_path. Returns its pid."""
    if os.name == "nt":
        detach = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        detach = {"start_new_session": True}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as log:
        return subprocess.Popen(command, cwd=APP_DIR, stdout=log, stderr=subprocess.STDOUT, **detach).pid


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_tree(process: subprocess.Popen) -> None:
    """End a child process and everything it started (a port forward runs ssh under the Brev CLI, and on Windows the
    CLI itself under wsl.exe). Waits for it."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)  # started with start_new_session, so the group is the process's
        except OSError:
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
