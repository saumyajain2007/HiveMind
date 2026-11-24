"""FastAPI application.

Run locally with:  uv run uvicorn marketsim_api.main:app --reload
Environment: MARKETSIM_DATA_DIR (default ./runs), MARKETSIM_CORS_ORIGINS, MARKETSIM_LOG_LEVEL,
MARKETSIM_LOG_JSON (1 = JSON lines, the default), MARKETSIM_MAX_JOBS (concurrent jobs, default 2),
MARKETSIM_EXECUTOR (process | thread), MARKETSIM_RUN_JOBS (0 = record runs without running them).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import marketsim

from . import __version__
from .datasets import DatasetStore
from .jobs import JobRegistry
from .log import RequestLogMiddleware, configure_logging, logger
from .routes import analysis, config, experiments, parse, results, runs, scenarios, stream
from .schemas import Health
from .settings import Settings
from .storage import Store

API_PREFIX = "/api/v1"


def health() -> Health:
    """Liveness probe; also reports the engine version the API was built against."""
    return Health(api_version=__version__, engine_version=marketsim.__version__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = Store(settings.data_dir)
        app.state.store = store
        app.state.datasets = DatasetStore(settings.data_dir)
        interrupted = store.fail_interrupted()
        app.state.jobs = (
            JobRegistry(store, settings.max_jobs, settings.executor) if settings.run_jobs else None
        )
        logger.info(
            "startup",
            extra={"data_dir": str(settings.data_dir), "version": __version__, "interrupted": interrupted},
        )
        yield
        if app.state.jobs is not None:
            app.state.jobs.shutdown()

    app = FastAPI(
        title="marketsim API",
        version=__version__,
        description="Agent-based market simulator: scenarios, runs and results.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1_000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.add_api_route("/api/health", health, methods=["GET"], response_model=Health, tags=["meta"])
    v1 = APIRouter(prefix=API_PREFIX)
    v1.add_api_route(
        "/health", health, methods=["GET"], response_model=Health, tags=["meta"], operation_id="health_v1"
    )
    v1.include_router(config.router)
    v1.include_router(scenarios.router)
    v1.include_router(runs.router)
    v1.include_router(stream.router)
    v1.include_router(results.router)
    v1.include_router(analysis.router)
    v1.include_router(parse.router)
    v1.include_router(experiments.router)
    app.include_router(v1)
    return app


app = create_app()
