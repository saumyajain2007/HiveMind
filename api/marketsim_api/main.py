"""FastAPI application entry point.

Skeleton only (issue #1). Schemas, run registry and streaming land in issues #16-#18.
Run locally with:  uv run --extra api uvicorn marketsim_api.main:app --reload
"""

from fastapi import FastAPI

import marketsim

from . import __version__

app = FastAPI(title="marketsim API", version=__version__)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe; also reports the engine version the API was built against."""
    return {"status": "ok", "api_version": __version__, "engine_version": marketsim.__version__}
