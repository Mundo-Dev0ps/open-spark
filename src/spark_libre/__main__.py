"""CLI entry point: ``python -m spark_libre`` or ``spark-libre``."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="spark-libre")
    parser.add_argument("--host", default=None, help="bind host (default 127.0.0.1, loopback only)")
    parser.add_argument("--port", type=int, default=None, help="bind port (default 8765)")
    parser.add_argument("--mock", action="store_true", help="use in-memory mock OBS (no real OBS)")
    parser.add_argument("--reload", action="store_true", help="dev: reload on file changes")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    settings = get_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.mock:
        settings.mock_obs = True
    if args.log_level:
        settings.log_level = args.log_level

    host, port = settings.bind_address()

    # Materialize back to env so the reloader subprocess inherits the same config.
    import os

    os.environ["SPARK_HOST"] = host
    os.environ["SPARK_PORT"] = str(port)
    os.environ["SPARK_MOCK_OBS"] = "1" if settings.mock_obs else "0"
    os.environ["SPARK_LOG_LEVEL"] = settings.log_level

    logging.getLogger(__name__).info(
        "Spark Libre starting on http://%s:%s (mock=%s)",
        host,
        port,
        settings.mock_obs,
    )

    uvicorn.run(
        "spark_libre.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
