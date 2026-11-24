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
pnpm -C web dev            # http://localhost:5173 (mock API by default, see below)
pnpm -C web test           # unit tests (Vitest + MSW)
pnpm -C web exec playwright install chromium   # once
pnpm -C web e2e            # accessibility (axe, both themes) + end-to-end
pnpm -C web build

# Git hooks (ruff, mypy, prettier, eslint on commit)
uv run pre-commit install
```

## Engine

```bash
uv run python -m marketsim.run_demo --agents 10000 --days 5 --runs 20   # plots + summary.json in outputs/
uv run python -m marketsim.calibration          # parameter-recovery test (≈1 min)
uv run python -m marketsim.backtest             # backtest on a synthetic series
```

### Backtesting on real data

Prices are a CSV with a header and one row per trading day, oldest first:

```csv
date,close
2024-01-02,185.64
2024-01-03,184.25
```

Events are a JSON list (or `{"events": [...]}`) in the same format as scenario events, except that `tick` is replaced by `date` (a date in the CSV) or `day` (a row index), plus an optional `time` (`"HH:MM"`, default `"09:00"`). Only events at or before each origin's close are used for that origin's forecast.

```json
[{"date": "2024-02-01", "time": "16:30", "kind": "earnings", "true_impact": -0.04,
  "sentiment": -0.6, "credibility": 0.95, "salience": 0.8, "complexity": 0.4, "seeding": "official"}]
```

```python
from marketsim.backtest import backtest, load_dated_events, load_price_csv

dates, closes = load_price_csv("prices.csv")
events = load_dated_events("events.json", dates)
res = backtest(closes, events, origins=range(30, len(closes) - 1), horizon=1, runs=20, dates=dates)
print(res.skill)   # 1 − mean CRPS(model) / mean CRPS(random walk); > 0 beats the random walk
```

For historical events, `true_impact` should come from `event_parser.abnormal_return_impact` (an event study) for *calibration only*; using it as a forecast input is lookahead leakage.

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

## Web app

React 19 + TypeScript + Vite, Tailwind 4 + shadcn/ui (Radix), Motion, TanStack Query, Zustand. The design is a night-mode trading terminal, with dark as the default and a light theme too. `/design` shows every token and component in both themes.

- **Mock API.** `web/.env.development` sets `VITE_API_MOCK=true`, so `pnpm dev` runs against an in-browser mock of the FastAPI routes plus a replayed live stream (MSW, `web/src/mocks`). A "MOCK DATA" tag in the top bar says so. Set `VITE_API_MOCK=false` and run the API on :8000 to use the real backend; Vite proxies `/api`. Production builds never include the mocks.
- **Live data.** `WS /api/v1/runs/{id}/stream` messages are defined in `web/src/lib/live/types.ts`; the real stream arrives with #17. Frames go into ring buffers outside React state, and subscribers re-render at most once per animation frame.
- **Shortcuts.** `Ctrl/⌘ K` opens the command palette. Charts can be read with the keyboard: focus a chart, then use ← →.
- **Accessibility.** The e2e suite runs axe (WCAG 2.1 AA, including colour contrast) on every page in both themes. Animations respect `prefers-reduced-motion`.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | Steps |
|---|---|
| `engine` | ruff check, ruff format --check, mypy, pytest `tests/` |
| `api` | OpenAPI spec up to date, pytest `api/tests/` |
| `web` | pnpm install --frozen-lockfile, API types up to date, eslint, prettier --check, tsc, vitest, vite build |
| `e2e` | Playwright + axe on every page in both themes, live-stream smoke test (mock API) |

## Branch protection (recommended)

The repo's owner chose to push the early skeleton work straight to `main`. Once the engine work starts, protect `main` under **Settings → Branches → Add rule**:

- Require a pull request before merging (1 approval, or 0 for a solo repo).
- Require status checks to pass: `engine`, `api`, `web`, `e2e`.
- Require branches to be up to date before merging.
- Block force pushes and deletions.

Feature work then goes on branches named after the issue (e.g. `feat/02-population`) and merges by PR.

## Placeholders

Every number in `marketsim/config.py` that is not fitted to data is marked `PLACEHOLDER`. [`DATA_SOURCES.md`](DATA_SOURCES.md) lists where each one should come from, and [`DECISIONS.md`](DECISIONS.md) records judgement calls.
