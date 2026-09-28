"""Close a running Brave and start the same profile with a debug port.

This is an explicit action. It closes every Brave window. It does not copy
cookies, and it does not create a second user-data directory.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

BRAVE_EXE = Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
DEBUG_PORT = 9222


def _browser_pids() -> list[int]:
    """Brave processes that are the browser, not a renderer or gpu child."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'brave.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    pids: list[int] = []
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _close_main_windows(pids: list[int]) -> None:
    if not pids:
        return
    joined = ",".join(str(pid) for pid in pids)
    script = (
        f"$ids = @({joined}); "
        "foreach ($id in $ids) { "
        "  $p = Get-Process -Id $id -ErrorAction SilentlyContinue; "
        "  if ($p) { [void]$p.CloseMainWindow() } "
        "}"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _wait_until_gone(timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _browser_pids():
            return True
        time.sleep(0.5)
    return not _browser_pids()


def relaunch_brave_for_debug() -> dict[str, object]:
    """Close Brave if it is open, then start it with remote debugging.

    Returns a status dict. Does not read cookies. Does not click any prompt.
    """
    if not BRAVE_EXE.is_file():
        return {"ok": False, "error": "brave_missing", "exe": str(BRAVE_EXE)}
    pids = _browser_pids()
    if pids:
        _close_main_windows(pids)
        if not _wait_until_gone():
            return {
                "ok": False,
                "error": "brave_still_open",
                "pids": _browser_pids(),
                "hint": "The profile is still locked, so a second Brave was not started.",
            }
    args = [
        str(BRAVE_EXE),
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--restore-last-session",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return {"ok": True, "closed_pids": pids, "port": DEBUG_PORT, "user_data": os.environ.get("LOCALAPPDATA", "")}
