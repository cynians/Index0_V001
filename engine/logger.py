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

    def _log(self, level, message):
        if not self._should_log(level):
            return

        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {message}")

    def debug(self, msg, key=None, interval=1.0):
        """
        Rate-limited debug log.

        key: unique identifier for this log line
        interval: minimum seconds between prints
        """
        if not self._should_log("DEBUG"):
            return

        now = time.time()

        if key is not None:
            last = self._last_log_times.get(key, 0)
            if now - last < interval:
                return
            self._last_log_times[key] = now

        self._log("DEBUG", msg)

    def info(self, msg):
        self._log("INFO", msg)

    def warn(self, msg):
        self._log("WARN", msg)

    def error(self, msg):
        self._log("ERROR", msg)


logger = Logger(level="DEBUG")