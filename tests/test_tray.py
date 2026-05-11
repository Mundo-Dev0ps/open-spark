"""Tray-app helper tests.

We exercise the testable parts (arg parsing, backend-probe loop, icon
generator) without importing :mod:`pywebview` or :mod:`pystray` so the
default test image — which deliberately has no GUI deps — keeps working.
"""

from __future__ import annotations

import http.server
import socket
import threading
from contextlib import closing
from typing import Iterator

import pytest

from spark_libre import tray


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib spelling)
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_args: object, **_kw: object) -> None:
        return  # silence


@pytest.fixture
def fake_backend() -> Iterator[str]:
    """Start a tiny HTTP server in a thread and yield its URL."""
    port = _free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), _OkHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/api/status"
    finally:
        server.shutdown()


def test_wait_for_backend_returns_true_when_up(fake_backend: str) -> None:
    assert tray._wait_for_backend(fake_backend, timeout=5.0, interval=0.1) is True


def test_wait_for_backend_returns_false_when_down() -> None:
    # Pick a port that's almost certainly closed.
    port = _free_port()  # bind+release so it's free *now* — server NOT started
    url = f"http://127.0.0.1:{port}/api/status"
    assert tray._wait_for_backend(url, timeout=0.5, interval=0.1) is False


def test_parse_args_defaults() -> None:
    ns = tray._parse_args([])
    assert ns.url.startswith("http://127.0.0.1")
    assert ns.no_tray is False
    assert ns.wait_timeout > 0


def test_parse_args_no_tray_flag() -> None:
    ns = tray._parse_args(["--no-tray", "--url", "http://example/x"])
    assert ns.no_tray is True
    assert ns.url == "http://example/x"


def test_make_icon_image_returns_pil_or_none() -> None:
    """Icon generator must be safe to call even if Pillow is missing."""
    out = tray._make_icon_image()
    if out is None:
        return  # Pillow not in the test image — fine
    # Otherwise it must be a PIL image with the requested size.
    assert getattr(out, "size", None) == (64, 64)


def test_main_exits_2_when_backend_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main returns code 2 (and does not import GUI deps) if backend is down."""
    monkeypatch.setattr(tray, "_wait_for_backend", lambda *a, **k: False)
    rc = tray.main(["--url", "http://127.0.0.1:1/", "--wait-timeout", "0"])
    assert rc == 2
