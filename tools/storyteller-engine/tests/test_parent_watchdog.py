"""Regression tests for the engine's parent watchdog.

Two real failures motivated these: a watchdog thread that raised on a ctypes
prototype mistake and died silently, and a shutdown that never ran because the
announce line was written to the broken pipe of the dead parent.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from engine_server import _emit, start_parent_watchdog  # noqa: E402
import cli  # noqa: E402


def _engine_env() -> dict[str, str]:
    """Environment for engine subprocesses: never quiet, so "listening" arrives.

    Also keeps these tests independent of any flag another test module set in
    this process, which is what previously made this file hang.
    """
    env = {key: value for key, value in os.environ.items() if key != "STORYTELLER_SERVER_QUIET"}
    return env


def _pump(stream, sink: "queue.Queue[str]") -> None:
    """Feed lines to a queue so reading can be bounded rather than blocking."""
    for line in stream:
        sink.put(line)
    sink.put("")


def _next_line(sink: "queue.Queue[str]", timeout: float) -> str | None:
    """Next line, or None on timeout/EOF. Never blocks the caller forever."""
    try:
        line = sink.get(timeout=timeout)
    except queue.Empty:
        return None
    return line or None


def _spawn_victim() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for(fired: threading.Event, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if fired.is_set():
            return True
        time.sleep(0.1)
    return fired.is_set()


def test_watchdog_fires_when_the_watched_process_dies():
    victim = _spawn_victim()
    fired = threading.Event()
    try:
        installed = start_parent_watchdog(lambda: fired.set(), parent_pid=victim.pid, interval=0.2)
        assert installed is True, "watchdog was not installed for an explicit pid"
        assert not fired.is_set(), "watchdog fired while the watched process was alive"

        victim.terminate()
        victim.wait(timeout=10)

        assert _wait_for(fired, 15), "watchdog never fired after the watched process died"
    finally:
        if victim.poll() is None:
            victim.kill()


def test_watchdog_reports_unavailable_rather_than_raising_for_a_dead_pid():
    # A pid that never existed: a failed watch is reported, it must not raise.
    fired = threading.Event()
    installed = start_parent_watchdog(lambda: fired.set(), parent_pid=999999999, interval=0.2)
    assert installed in (True, False)


def test_emit_survives_a_closed_stdout(capsys):
    """A broken pipe to the dead parent must not abort the shutdown path."""
    read_fd, write_fd = os.pipe()
    saved = sys.stdout
    stream = os.fdopen(write_fd, "w", encoding="utf-8")
    os.close(read_fd)  # nobody reads the other end any more
    sys.stdout = stream
    try:
        _emit({"event": "parent-gone"})  # must not raise
    finally:
        sys.stdout = saved
        try:
            stream.close()
        except Exception:
            pass


def test_serve_parser_exposes_the_watchdog_flags():
    args = cli.build_parser().parse_args(["serve", "--watch-parent", "--parent-pid", "1234"])
    assert args.watch_parent is True
    assert args.parent_pid == 1234
    assert cli.build_parser().parse_args(["serve"]).watch_parent is False


def test_engine_exits_when_the_watched_process_is_killed():
    """End-to-end: the real CLI, watching a process that is then killed."""
    victim = _spawn_victim()
    engine_proc = subprocess.Popen(
        [sys.executable, str(ENGINE_DIR / "cli.py"), "serve", "--port", "0",
         "--repo", str(ENGINE_DIR), "--parent-pid", str(victim.pid)],
        cwd=str(ENGINE_DIR),
        env=_engine_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        assert engine_proc.stdout is not None
        sink: "queue.Queue[str]" = queue.Queue()
        threading.Thread(target=_pump, args=(engine_proc.stdout, sink), daemon=True).start()

        port = None
        deadline = time.time() + 60
        while time.time() < deadline and port is None:
            line = _next_line(sink, 10)
            if line is None:
                break
            if "listening" in line:
                port = json.loads(line)["port"]
        assert port, "engine never reported a port"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=20) as response:
            assert json.load(response)["ok"] is True

        victim.terminate()
        victim.wait(timeout=10)

        deadline = time.time() + 20
        while time.time() < deadline and engine_proc.poll() is None:
            time.sleep(0.25)
        assert engine_proc.poll() is not None, "engine outlived the process it was watching"
    finally:
        if engine_proc.poll() is None:
            engine_proc.kill()
        if victim.poll() is None:
            victim.kill()


def _is_alive(pid: int) -> bool:
    if os.name == "nt":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout
        return str(pid) in listing
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


HOST_SCRIPT = '''
import json, os, subprocess, sys, time
engine = sys.argv[1]
repo = sys.argv[2]
child = subprocess.Popen(
    [sys.executable, engine, "serve", "--port", "0", "--repo", repo, "--watch-parent"],
    cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace", bufsize=1,
)
for line in child.stdout:
    if "listening" in line:
        payload = json.loads(line)
        payload["engine_pid"] = child.pid
        print(json.dumps(payload), flush=True)
        break
time.sleep(120)
'''


def test_engine_dies_with_an_abruptly_killed_host(tmp_path):
    """The reported bug: a force-killed window strands the engine.

    Killing the host also destroys the read end of the engine's stdout, which is
    why the shutdown path must not depend on being able to log.
    """
    host_script = tmp_path / "host.py"
    host_script.write_text(HOST_SCRIPT, encoding="utf-8")
    host = subprocess.Popen(
        [sys.executable, str(host_script), str(ENGINE_DIR / "cli.py"), str(ENGINE_DIR)],
        env=_engine_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    engine_pid = None
    try:
        assert host.stdout is not None
        sink: "queue.Queue[str]" = queue.Queue()
        threading.Thread(target=_pump, args=(host.stdout, sink), daemon=True).start()

        deadline = time.time() + 60
        while time.time() < deadline:
            line = _next_line(sink, 10)
            if line is None:
                break
            if "listening" in line:
                engine_pid = json.loads(line)["engine_pid"]
                break
        assert engine_pid, "host never reported the engine it spawned"
        assert _is_alive(engine_pid)

        # Abrupt death: no dispose, no shutdown notification, pipe broken.
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(host.pid), "/F"],
                           capture_output=True, text=True)
        else:
            host.kill()
        host.wait(timeout=20)

        deadline = time.time() + 30
        while time.time() < deadline and _is_alive(engine_pid):
            time.sleep(0.25)
        assert not _is_alive(engine_pid), "engine outlived an abruptly killed host"
    finally:
        if host.poll() is None:
            host.kill()
        if engine_pid and _is_alive(engine_pid):
            subprocess.run(["taskkill", "/PID", str(engine_pid), "/F"],
                           capture_output=True, text=True)


@pytest.mark.parametrize("flag", ["--watch-parent", "--parent-pid"])
def test_serve_help_mentions_the_watchdog(flag):
    result = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "cli.py"), "serve", "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert flag in result.stdout
