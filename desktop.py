"""Desktop launcher: the Streamlit app in a pywebview window, with a shutdown
that actually shuts down.

Replaces ``streamlit_desktop_app.start_desktop_app`` (v0.3.4), whose teardown is::

    streamlit_process.terminate()
    streamlit_process.join()          # <- no timeout

On macOS the Streamlit/Tornado child often ignores SIGTERM, so that bare
``join()`` blocks the parent forever — the window closes but the app "loads
forever" and never quits. Any Chromium a publish spawned is also left orphaned.

This launcher owns the teardown: ``terminate -> join(timeout) -> kill``, and
starts the child in its own process group (POSIX) so killing the group reaps the
orphaned Chromium too. Same pywebview window as before, just a bounded exit.

Run from source with ``python run_desktop.py``; frozen into the .app by
``build_app.sh`` (PyInstaller, entry point = this file).
"""
from __future__ import annotations

import atexit
import multiprocessing
import os
import signal
import socket
import sys
import time
import traceback
from typing import Dict, Optional

TITLE = "My Maps Generator"
WIDTH, HEIGHT = 1024, 768
JOIN_TIMEOUT = 5  # seconds to wait after terminate() before SIGKILL
# Theme flags mirror the packaged build so the window looks identical.
THEME = {"theme.base": "light", "theme.primaryColor": "#2563EB"}


def _script_path() -> str:
    """streamlit_app.py, whether running frozen (_MEIPASS) or from source."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "streamlit_app.py")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _run_streamlit(script: str, port: int, options: Dict[str, str]) -> None:
    """Child entry point: run `streamlit run <script>` in-process."""
    # New session/group (POSIX) so the parent can kill Streamlit *and* any
    # Chromium it spawns as one group on exit.
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass
    from streamlit.web import cli as stcli

    argv = [
        "streamlit", "run", script,
        "--server.address=localhost", f"--server.port={port}",
        "--server.headless=true", "--global.developmentMode=false",
    ]
    argv += [f"--{k}={v}" for k, v in options.items()]
    sys.argv = argv
    stcli.main()


def _wait_for_server(port: int, timeout: float = 60.0) -> None:
    """Block until the child's port answers. 60s because a frozen macOS app's
    first launch unpacks + imports Streamlit from a cold Gatekeeper scan, which
    can take far longer than a dev run (20s used to abort a healthy start)."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    url = f"http://localhost:{port}"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return  # server answered (any status) -> it's up
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    raise TimeoutError("Streamlit server did not start in time.")


def _killpg(pid: int, sig: int) -> None:
    if not hasattr(os, "killpg"):
        return
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _shutdown(proc: multiprocessing.Process) -> None:
    """Stop the Streamlit child (and its group) within JOIN_TIMEOUT. The fix."""
    if proc.pid is None or not proc.is_alive():
        return
    _killpg(proc.pid, signal.SIGTERM)  # reaps orphaned Chromium on POSIX
    proc.terminate()
    proc.join(JOIN_TIMEOUT)
    if proc.is_alive():
        _killpg(proc.pid, signal.SIGKILL)
        proc.kill()
        proc.join(JOIN_TIMEOUT)


def _spawn(options: Dict[str, str]) -> "tuple[multiprocessing.Process, int]":
    port = _free_port()
    proc = multiprocessing.Process(
        target=_run_streamlit, args=(_script_path(), port, options)
    )
    proc.start()
    return proc, port


def start(options: Optional[Dict[str, str]] = None, title: str = TITLE) -> None:
    """Launch Streamlit in a child process inside a pywebview window."""
    opts = {**THEME, **(options or {})}
    proc, port = _spawn(opts)
    # On macOS pywebview terminates the Cocoa app on window close and may not
    # return from webview.start(), so the finally below can be skipped — atexit
    # still reaps the setsid-detached child. _shutdown() is idempotent.
    atexit.register(_shutdown, proc)
    try:
        _wait_for_server(port)
        import webview

        webview.create_window(
            title, f"http://localhost:{port}", width=WIDTH, height=HEIGHT
        )
        webview.start()
    except Exception:
        traceback.print_exc()  # log it; the finally below still exits cleanly
    finally:
        # Hard exit. On macOS the window closes but the process lingers —
        # pywebview's Cocoa/objc runtime and multiprocessing's spawn machinery
        # leave non-daemon threads behind, so returning normally hangs in the
        # interpreter's join-all-threads shutdown: the app "can't be closed" and
        # keeps bouncing in the Dock. The Streamlit child is reaped first, so
        # there's nothing left to flush.
        _shutdown(proc)
        os._exit(0)


def _selfcheck() -> None:
    """`python desktop.py --selfcheck`: start the child, confirm the port
    answers, then confirm _shutdown() actually stops it. No webview/browser."""
    proc, port = _spawn(dict(THEME))
    try:
        _wait_for_server(port)
        assert proc.is_alive(), "child died before serving"
    finally:
        _shutdown(proc)
    assert not proc.is_alive(), "child still alive after _shutdown()"
    print("desktop selfcheck OK")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for spawn in a frozen app
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        start()
