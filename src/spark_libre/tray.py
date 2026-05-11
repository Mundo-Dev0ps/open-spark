"""Native desktop wrapper around the Spark Libre web UI.

Why this exists:
* The backend is a local FastAPI server. By itself it requires the user
  to remember the localhost URL and keep a browser tab open.
* This module wraps that experience in a native OS window plus a system
  tray icon, so the app feels like any other desktop app even though it
  is implemented as a web stack underneath.

Runtime model:
* The backend is expected to already be running (``./start.sh up-d`` or
  the user installed and started the daemon some other way). The tray
  app polls ``/api/status`` and shows a connecting state until the
  backend is reachable.
* The window points at the existing ``/ui/`` static page; no JS or HTML
  duplication.
* The tray icon offers Show / Reload / Open in browser / Quit.

Install (host, not in the container):

    pip install --user "spark-libre[tray]"
    spark-libre-tray
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import webbrowser
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8765/ui/"
STATUS_URL = "http://127.0.0.1:8765/api/status"
WINDOW_TITLE = "Spark Libre"


# --- Importable helpers (kept testable without GUI deps) -------------------

def _wait_for_backend(url: str, *, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Poll ``GET url`` until it returns 200 or the timeout elapses.

    Used by the tray app at startup so the window doesn't open against a
    backend that hasn't bound the port yet. Returns True on success.
    """
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=interval) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("backend probe error: %s", e)
        time.sleep(interval)
    return False


def _make_icon_image(size: int = 64):
    """Generate a tiny in-memory PNG icon (no file dependency).

    Picks the brand accent color used by the web UI so the system tray
    icon matches. Falls back to a plain square if Pillow is not yet
    available — this lets ``import spark_libre.tray`` work in the test
    image too.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        return None

    img = Image.new("RGBA", (size, size), (255, 177, 74, 255))
    d = ImageDraw.Draw(img)
    # Simple "S" glyph centered.
    text = "S"
    try:
        bbox = d.textbbox((0, 0), text)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        w, h = 12, 16
    d.text(((size - w) // 2, (size - h) // 2 - 4), text, fill=(26, 17, 0, 255))
    return img


# --- Entry point ----------------------------------------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="spark-libre-tray", description=__doc__)
    p.add_argument(
        "--url",
        default=os.environ.get("SPARK_TRAY_URL", DEFAULT_URL),
        help="Backend UI URL to load (default: %(default)s)",
    )
    p.add_argument(
        "--no-tray",
        action="store_true",
        help="Skip the system-tray icon (just the window).",
    )
    p.add_argument(
        "--wait-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the backend before opening the window.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=os.environ.get("SPARK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    log.info("waiting for backend at %s", STATUS_URL)
    if not _wait_for_backend(STATUS_URL, timeout=args.wait_timeout):
        sys.stderr.write(
            "Spark Libre backend is not reachable. Start it first:\n"
            "    ./start.sh up-d\n"
        )
        return 2

    # Imports are lazy so the rest of the module is importable in
    # headless environments (CI, container) where pywebview/pystray
    # cannot initialize.
    try:
        import webview  # type: ignore
    except ImportError:
        sys.stderr.write(
            "Missing GUI dependencies. Install the tray extra:\n"
            "    pip install --user 'spark-libre[tray]'\n"
        )
        return 3

    window = webview.create_window(
        WINDOW_TITLE,
        args.url,
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
    )

    def _open_in_browser() -> None:
        webbrowser.open(args.url)

    def _reload() -> None:
        try:
            window.evaluate_js("location.reload()")
        except Exception as e:
            log.warning("reload failed: %s", e)

    if not args.no_tray:
        try:
            import pystray  # type: ignore
        except ImportError:
            log.warning("pystray missing; skipping tray icon")
        else:
            icon_img = _make_icon_image()
            if icon_img is None:
                log.warning("Pillow missing; skipping tray icon")
            else:
                def _show(_icon: Any, _item: Any = None) -> None:
                    try:
                        window.show()
                    except Exception:  # noqa: BLE001
                        pass

                def _hide(_icon: Any, _item: Any = None) -> None:
                    try:
                        window.hide()
                    except Exception:  # noqa: BLE001
                        pass

                def _quit(icon: Any, _item: Any = None) -> None:
                    try:
                        webview.destroy_window()
                    finally:
                        icon.stop()

                menu = pystray.Menu(
                    pystray.MenuItem("Show window", _show, default=True),
                    pystray.MenuItem("Hide window", _hide),
                    pystray.MenuItem("Reload", lambda *_: _reload()),
                    pystray.MenuItem("Open in browser", lambda *_: _open_in_browser()),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Quit", _quit),
                )
                icon = pystray.Icon("spark-libre", icon_img, WINDOW_TITLE, menu)
                threading.Thread(target=icon.run, daemon=True).start()

    log.info("opening native window at %s", args.url)
    webview.start()  # blocks until window closed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
