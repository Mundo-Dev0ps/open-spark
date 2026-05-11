"""FastAPI app + lifespan. Loopback only."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
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


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )


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
        try:
            await obs.disconnect()
        except Exception:
            pass

    app = FastAPI(
        title="Open Spark",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    app.include_router(api_router)

    if STATIC_DIR.exists():
        app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    @app.get("/")
    async def root():
        return RedirectResponse("/ui/")

    return app


# Convenience for `uvicorn open_spark.main:app`
app = create_app()
