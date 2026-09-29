import time


class Logger:
    LEVELS = {
        "DEBUG": 0,
        "INFO": 1,
        "WARN": 2,
        "ERROR": 3,
    }

    def __init__(self, level="INFO"):
        self.level = level
        self._last_log_times = {}

    def _should_log(self, level):
        return self.LEVELS[level] >= self.LEVELS[self.level]

    def _log(self, level, message, key=None, interval=1.0):
        if not self._should_log(level):
            return

        if key is not None:
            now = time.time()
            last = self._last_log_times.get(key, 0)
            if now - last < interval:
                return
            self._last_log_times[key] = now

        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {message}")

    def debug(self, msg, key=None, interval=1.0):
        """
        Rate-limited debug log.

        key: unique identifier for this log line
        interval: minimum seconds between prints
        """
        self._log("DEBUG", msg, key=key, interval=interval)

    def info(self, msg, key=None, interval=1.0):
        self._log("INFO", msg, key=key, interval=interval)

    def warn(self, msg, key=None, interval=1.0):
        self._log("WARN", msg, key=key, interval=interval)

    def error(self, msg, key=None, interval=1.0):
        self._log("ERROR", msg, key=key, interval=interval)


logger = Logger(level="DEBUG")
