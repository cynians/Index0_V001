"""Persistent diagnostics for uncaught Python and native runtime failures."""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path


_REPORT_STREAM = None
_REPORT_PATH = None
_LOCK = threading.RLock()


def _timestamp():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write(message):
    if _REPORT_STREAM is None:
        return
    with _LOCK:
        _REPORT_STREAM.write(f"[{_timestamp()}] {message}\n")
        _REPORT_STREAM.flush()


def record_runtime_stage(stage):
    _write(f"STAGE: {stage}")


def record_uncaught_exception(exc_type, exc_value, exc_traceback, *, source="main"):
    if _REPORT_STREAM is None:
        return
    with _LOCK:
        _REPORT_STREAM.write(f"[{_timestamp()}] UNCAUGHT EXCEPTION ({source})\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=_REPORT_STREAM)
        _REPORT_STREAM.flush()


def mark_clean_shutdown():
    _write("CLEAN SHUTDOWN")


def install_crash_reporting(project_root):
    """Install one process-wide report before pygame or repository startup."""
    global _REPORT_PATH, _REPORT_STREAM
    if _REPORT_STREAM is not None:
        return _REPORT_PATH
    report_root = Path(project_root).resolve() / ".cache" / "crash_reports"
    report_root.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH = report_root / "latest.log"
    _REPORT_STREAM = _REPORT_PATH.open("w", encoding="utf-8", buffering=1)
    _write(f"Index0 process started with Python {sys.version.split()[0]}")
    faulthandler.enable(file=_REPORT_STREAM, all_threads=True)

    original_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        record_uncaught_exception(exc_type, exc_value, exc_traceback, source="main-thread")
        original_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    original_thread_hook = getattr(threading, "excepthook", None)
    if original_thread_hook is not None:
        def thread_hook(args):
            thread_name = getattr(getattr(args, "thread", None), "name", "unknown-thread")
            record_uncaught_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                source=thread_name,
            )
            original_thread_hook(args)

        threading.excepthook = thread_hook
    return _REPORT_PATH
