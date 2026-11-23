# HiveMind: marketsim

An agent-based simulator for a single stock. Agents with correlated traits live on several social platforms. News and rumours spread between them, change what they believe, and they trade on those beliefs in a batch auction. Running it many times gives a distribution of price paths, which is then calibrated against history and backtested against a random walk.

> **Status: skeleton (issue #1).** Tooling and CI are in place; the engine, API and web app are built in issues #2–#25. See [`issues.md`](issues.md) for the plan and [`HANDOFF.md`](HANDOFF.md) for the engine spec.

## Repository layout

```
marketsim/        engine package (pure Python + NumPy, no web code)
api/marketsim_api FastAPI service around the engine
web/              React + TypeScript + Vite front end
tests/            engine tests        api/tests/  API tests
docs/             design notes (source of truth, not edited)
```

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/) and Node.js ≥ 20 with corepack (it ships with Node).

```bash
# Python: engine + API + dev tools (uv installs Python 3.12 if needed)
uv sync --all-extras
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy

# API: http://127.0.0.1:8000/docs (interactive OpenAPI docs)
uv run uvicorn marketsim_api.main:app --reload

# Web
corepack enable            # once; or prefix commands with `corepack`
pnpm -C web install
pnpm -C web dev            # http://localhost:5173
pnpm -C web build

# Git hooks (ruff, mypy, prettier, eslint on commit)
uv run pre-commit install
```

## API

FastAPI service in `api/marketsim_api`. Everything except `/api/health` lives under `/api/v1`:

| Endpoint | Purpose |
|---|---|
| `GET /config/defaults` | Default parameters (from `marketsim/config.py`) and an empty scenario |
| `GET /config/schema` | Every parameter with default, range, description and `placeholder` flag, plus enums and the tick clock |
| `POST/GET/PUT/DELETE /scenarios` | Saved scenarios: agent count, days, seed and scheduled events |
| `POST /runs` | Record a run (`queued`) from a saved or inline scenario; execution arrives in #17 |
| `GET /runs`, `GET/DELETE /runs/{id}` | Run index (paged, filter by status) and run details |

The parameter models are generated from the `config.py` dataclasses, so adding a field there adds it to the API (give it a range in `config_schema.FIELD_RANGES`; a test enforces this). Runs are stored under `MARKETSIM_DATA_DIR` (default `./runs`): `index.sqlite3` plus `runs/<id>/spec.json`. Each run has a `spec_hash`, and equal hashes mean identical results.

After changing the API, regenerate the spec and the web types (CI checks both):

```bash
uv run python -m marketsim_api.export_openapi
pnpm -C web gen:api
```

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | Steps |
|---|---|
| `engine` | ruff check, ruff format --check, mypy, pytest `tests/` |
| `api` | OpenAPI spec up to date, pytest `api/tests/` |
| `web` | pnpm install --frozen-lockfile, API types up to date, eslint, prettier --check, tsc, vitest, vite build |

## Branch protection (recommended)

The repo's owner chose to push the early skeleton work straight to `main`. Once the engine work starts, protect `main` under **Settings → Branches → Add rule**:

- Require a pull request before merging (1 approval, or 0 for a solo repo).
- Require status checks to pass: `engine`, `api`, `web`.
- Require branches to be up to date before merging.
- Block force pushes and deletions.

Feature work then goes on branches named after the issue (e.g. `feat/02-population`) and merges by PR.

## Placeholders

Every number in `marketsim/config.py` that is not fitted to data is marked `PLACEHOLDER`. [`DATA_SOURCES.md`](DATA_SOURCES.md) lists where each one should come from, and [`DECISIONS.md`](DECISIONS.md) records judgement calls.
