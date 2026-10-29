"""Lightweight LAN server that hands a pixel canvas to the companion web app
(running in a browser on another device, e.g. a pen-enabled tablet) and takes
the finished drawing back.

Stdlib-only by design: the repo has no HTTP framework dependency, and this is
a small, single-purpose bridge, not a general web app.
"""

import base64
import json
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8765
PORT_SCAN_RANGE = 6
WEB_DIR = Path(__file__).resolve().parent / "web"


def _lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class CompanionServer:
    """Holds exactly one outgoing canvas and one incoming result at a time.

    This is a single-user, single-companion prototype: sending a new canvas
    replaces whatever was pending before.
    """

    def __init__(self, port=DEFAULT_PORT):
        self._lock = threading.Lock()
        self._outgoing = None
        self._incoming = None
        self.port = port
        self._httpd = ThreadingHTTPServer(("0.0.0.0", port), _build_handler(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="index0-companion-server", daemon=True
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def lan_url(self):
        return f"http://{_lan_ip()}:{self.port}/"

    def publish_canvas(self, width, height, png_bytes, label=""):
        token = uuid.uuid4().hex[:12]
        with self._lock:
            self._outgoing = {
                "token": token,
                "width": int(width),
                "height": int(height),
                "label": str(label),
                "png_base64": base64.b64encode(png_bytes).decode("ascii"),
            }
            self._incoming = None
        return token

    def current_canvas(self):
        with self._lock:
            return dict(self._outgoing) if self._outgoing else None

    def submit_result(self, token, width, height, png_bytes):
        with self._lock:
            self._incoming = {
                "token": str(token),
                "width": int(width),
                "height": int(height),
                "png_bytes": png_bytes,
            }

    def take_result(self, expected_token):
        """Return and clear the pending result iff it answers expected_token."""
        with self._lock:
            result = self._incoming
            if result is None or result.get("token") != expected_token:
                return None
            self._incoming = None
            return result


def _build_handler(server_obj):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _write_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._serve_index()
            elif self.path == "/canvas":
                self._write_json(server_obj.current_canvas())
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/canvas":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8"))
                token = payload["token"]
                width = int(payload["width"])
                height = int(payload["height"])
                png_bytes = base64.b64decode(payload["png_base64"])
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_error(400, str(exc))
                return
            server_obj.submit_result(token, width, height, png_bytes)
            self._write_json({"ok": True})

        def _serve_index(self):
            try:
                data = (WEB_DIR / "index.html").read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


_singleton_lock = threading.Lock()
_singleton = None


def get_server():
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            return _singleton
        last_exc = None
        for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_RANGE):
            try:
                candidate = CompanionServer(port)
            except OSError as exc:
                last_exc = exc
                continue
            candidate.start()
            _singleton = candidate
            return _singleton
        raise RuntimeError(f"Could not start companion server: {last_exc}")
