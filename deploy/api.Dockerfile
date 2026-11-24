# marketsim API: FastAPI + the engine, run by uvicorn. Jobs run in a process pool inside the container.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app

# dependencies first (cached unless the lockfile changes)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra api --no-install-project

COPY marketsim ./marketsim
COPY api ./api
COPY docs/experiments ./docs/experiments
RUN uv sync --locked --no-dev --extra api

ENV MARKETSIM_DATA_DIR=/data MARKETSIM_MAX_JOBS=2 MARKETSIM_CORS_ORIGINS=http://localhost:8080
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status == 200 else 1)"
CMD ["uvicorn", "marketsim_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
