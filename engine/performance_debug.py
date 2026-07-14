import time


class PerformanceDebug:
    """Low-overhead, one-line-per-second timing summaries for interactive spikes."""

    def __init__(self):
        self.enabled = False
        self._samples = {}
        self._last_spike_times = {}
        self._last_flush = time.perf_counter()

    def set_enabled(self, enabled, announce=True):
        enabled = bool(enabled)
        changed = enabled != self.enabled
        self.enabled = enabled
        self._samples.clear()
        self._last_spike_times.clear()
        self._last_flush = time.perf_counter()
        if announce and changed:
            state = "enabled" if enabled else "disabled"
            print(f"[PERF] diagnostics {state}")

    def record(self, name, elapsed_ms, detail=""):
        if not self.enabled:
            return
        try:
            elapsed_ms = float(elapsed_ms)
        except (TypeError, ValueError):
            return
        key = (str(name), str(detail or ""))
        sample = self._samples.setdefault(key, [0, 0.0, 0.0])
        sample[0] += 1
        sample[1] += elapsed_ms
        sample[2] = max(sample[2], elapsed_ms)
        now = time.perf_counter()
        if elapsed_ms >= 50.0 and now - self._last_spike_times.get(key, 0.0) >= 0.5:
            suffix = f" {key[1]}" if key[1] else ""
            print(f"[PERF] SPIKE {key[0]}{suffix} elapsed={elapsed_ms:.2f}ms")
            self._last_spike_times[key] = now
        self._flush_if_due()

    def _flush_if_due(self):
        now = time.perf_counter()
        if now - self._last_flush < 1.0:
            return
        for (name, detail), (count, total_ms, max_ms) in sorted(self._samples.items()):
            suffix = f" {detail}" if detail else ""
            print(
                f"[PERF] {name}{suffix} count={count} "
                f"avg={total_ms / max(1, count):.2f}ms max={max_ms:.2f}ms"
            )
        self._samples.clear()
        self._last_flush = now


performance_debug = PerformanceDebug()
