"""FastAPI app + lifespan. Loopback only."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import secrets_store
from .api.routes import router as api_router
from .config import Settings, get_settings
from .obs_client import OBSClientProtocol, make_client
from .overlays import OverlayStore

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class AppState:
    settings: Settings
    obs: OBSClientProtocol
    overlays: OverlayStore


class _JsonLogFormatter(logging.Formatter):
    """One-line JSON per record: ts, level, logger, msg, + request id
    when the access middleware put one on the record."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _setup_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    # JSON in containers / when OPENSPARK_LOG_JSON=1; human format locally.
    if os.environ.get("OPENSPARK_LOG_JSON", "1").lower() in {"1", "true", "yes"}:
        handler.setFormatter(_JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
        )
    root.addHandler(handler)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _setup_logging(settings.log_level)
    settings.bind_address()  # raise if non-loopback was sneaked in

    obs = make_client(
        mock=settings.mock_obs,
        host=settings.obs_host,
        port=settings.obs_port,
        password=secrets_store.get_obs_password(),
    )
    overlays = OverlayStore()
    state = AppState(settings=settings, obs=obs, overlays=overlays)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await obs.connect()
        except Exception as e:
            log.warning("OBS connect failed at startup (%s). UI will reflect this.", e)
        app.state.spark = state
        yield
        with suppress(Exception):
            await obs.disconnect()

    app = FastAPI(
        title="Open Spark",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.monotonic()
        try:
            resp = await call_next(request)
        except Exception:
            logging.getLogger("open_spark.access").error(
                "%s %s -> unhandled",
                request.method,
                request.url.path,
                extra={"request_id": rid},
                exc_info=True,
            )
            raise
        dur_ms = int((time.monotonic() - start) * 1000)
        logging.getLogger("open_spark.access").info(
            "%s %s -> %s (%dms)",
            request.method,
            request.url.path,
            resp.status_code,
            dur_ms,
            extra={"request_id": rid},
        )
        resp.headers["x-request-id"] = rid
        return resp

    app.include_router(api_router)

    if STATIC_DIR.exists():
        app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    @app.get("/")
    async def root():
        return RedirectResponse("/ui/")

    return app


# Convenience for `uvicorn open_spark.main:app`
app = create_app()
