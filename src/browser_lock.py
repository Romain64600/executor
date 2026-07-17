"""Cross-process mutual exclusion for the ONE browser tab.

OP1 (audit 2026-07-17): the CDP architecture drives a single Chrome tab
(`_page_ws_path` picks pages[0]), and BOTH the CLI scripts and the admin
service's spawned children navigate it. The admin has an in-process mutex, but
nothing stopped a human running ``scripts/05_submit.py`` while the admin was
mid-extract — two navigators corrupt each other's scans (and, on the write
path, each other's modals).

``browser_lock()`` is an advisory ``flock`` on ``state/browser.lock``, taken
non-blocking by every stage that opens a CDP session (02 extract, 05 submit in
all its modes, 00b login). The admin needs no direct change: it spawns those
same scripts, so its children inherit the protection. ``flock`` is released by
the kernel when the holder dies — no stale-lock cleanup, no daemon.

Fail-closed: if the lock is busy, the stage refuses to start (exit 2 at the
CLI), never queues, never shares the tab. Standard library only.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

LOCK_FILENAME = "browser.lock"


class BrowserBusyError(RuntimeError):
    """Another process currently drives the browser tab."""


@contextmanager
def browser_lock(repo_root: Path, *, label: str) -> Iterator[None]:
    """Hold the exclusive advisory browser lock for the duration of the block.

    ``label`` names the holder ("05_submit --submit", "admin extract", …) and
    is written into the lock file so the refused party's error says WHO holds
    the tab, not just that it is busy.
    """

    state_dir = Path(repo_root) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / LOCK_FILENAME
    handle = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError) as exc:
            handle.seek(0)
            holder = handle.read().strip()
            raise BrowserBusyError(
                "browser tab busy — held by "
                + (holder or "another process")
                + " (state/browser.lock)"
            ) from exc
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        handle.seek(0)
        handle.truncate()
        handle.write(f"{label} pid={os.getpid()} since {stamp}\n")
        handle.flush()
        try:
            yield
        finally:
            try:
                handle.seek(0)
                handle.truncate()
                handle.flush()
            except OSError:
                pass  # releasing matters more than emptying the label
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
