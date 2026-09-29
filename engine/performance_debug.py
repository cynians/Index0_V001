import time
from contextlib import contextmanager


class PerformanceDebug:
    """Spike-only interactive timing.

    When enabled, any timed operation that runs longer than ``SPIKE_MS`` prints a
    single ``[PERF] SPIKE ...`` line (rate limited per operation). There is no
    periodic summary ticker -- the only output is a spike, so a frozen frame is
    immediately traceable to the operation that caused it.
    """

    SPIKE_MS = 50.0
    SPIKE_REPEAT_COOLDOWN_S = 0.5

    def __init__(self):
        self.enabled = False
        self._last_spike_times = {}

    def set_enabled(self, enabled, announce=True):
        enabled = bool(enabled)
        changed = enabled != self.enabled
        self.enabled = enabled
        self._last_spike_times.clear()
        if announce and changed:
            state = "enabled" if enabled else "disabled"
            print(f"[PERF] diagnostics {state} (spikes >= {self.SPIKE_MS:.0f}ms)")

    def record(self, name, elapsed_ms, detail=""):
        if not self.enabled:
            return
        try:
            elapsed_ms = float(elapsed_ms)
        except (TypeError, ValueError):
            return
        if elapsed_ms < self.SPIKE_MS:
            return
        key = (str(name), str(detail or ""))
        now = time.perf_counter()
        if now - self._last_spike_times.get(key, 0.0) < self.SPIKE_REPEAT_COOLDOWN_S:
            return
        self._last_spike_times[key] = now
        suffix = f" {key[1]}" if key[1] else ""
        print(f"[PERF] SPIKE {key[0]}{suffix} elapsed={elapsed_ms:.1f}ms")

    @contextmanager
    def measure(self, name, detail=""):
        """``with performance_debug.measure("edit.relayout", detail): ...``

        No-op (aside from generator overhead) when diagnostics are disabled.
        """
        if not self.enabled:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter() - started) * 1000.0, detail)


performance_debug = PerformanceDebug()
