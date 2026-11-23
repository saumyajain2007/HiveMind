# Decisions

Every judgement call, simplification and `xfail` made while building marketsim, newest last.
Each entry: **date · issue · decision**, then a line of rationale.

## Process

- **2026-11-23 · #1 · Skeleton pushed straight to `main`.** The repo owner asked for issue #1 to be pushed directly to `main`, which overrides the handoff's "never commit to main" rule for this work. The README recommends turning on branch protection before engine work starts.
- **2026-11-23 · #1 · One Python project, two packages.** `marketsim` (engine) and `api/marketsim_api` are built from one `pyproject.toml` with hatchling. The API's dependencies live in the `api` extra, so the engine can still be installed without any web stack.
- **2026-11-23 · #1 · Python 3.12 pinned for development** (`.python-version`). `requires-python >=3.11` as in the handoff, and CI tests both 3.11 and 3.12 for the engine.
- **2026-11-23 · #1 · `config.py` excluded from `ruff format`.** It is the hand-written design-phase source of truth; linting still applies.
- **2026-11-23 · #1 · React 19 instead of the React 18 named in `issues.md`.** It is the current release and shadcn/ui targets it; nothing in the plan depends on 18.
- **2026-11-23 · #1 · TypeScript pinned to 6.0.x.** TypeScript 7 (the native port) is out, but `typescript-eslint` 8.x supports only `<6.1`. Move to 7 when typescript-eslint does.
- **2026-11-23 · #1 · `httpx2` instead of `httpx` for the API test client.** Current Starlette deprecates `httpx` in `TestClient`.
- **2026-11-23 · #1 · Pre-commit hooks are local (`language: system`).** They call `uv run` / `pnpm`, so hook versions always match the lockfiles. Ruff uses `force-exclude` so `config.py` stays unformatted even when pre-commit passes it by name.
- **2026-11-23 · #1 · pnpm through corepack.** Pinned with `packageManager` in `web/package.json`, so nobody needs a global pnpm install.

## Model

_(filled in from issue #2 onward)_

## Simplifications

_(none yet)_

## xfails

_(none yet)_

## Results

### Parameter-recovery test (#12)

_(pending)_

### Benchmarks (#15)

_(pending)_
